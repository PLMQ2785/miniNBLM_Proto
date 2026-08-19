import pytest

from app.clients.llm_client import LLMClient
from app.services.evidence_coverage import EvidenceMatrix, EvidenceMatrixGoal
from app.services.generator import INSUFFICIENT_EVIDENCE_ANSWER, StreamingAnswer
from app.services.retriever import RetrievedChunk


@pytest.fixture
def retrieved_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=10,
        document_id=20,
        document_title="lesson.pdf",
        content="낙상 예방 교육 내용",
        page_start=3,
        page_end=3,
        score=0.9,
        source_refs={"page": 3},
    )


def test_grounded_answer_streams_deltas_and_keeps_sources(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    monkeypatch.setattr(
        LLMClient,
        "stream_chat_completion",
        lambda self, messages, **kwargs: iter(
            ["자료에서는 ", "낙상 예방 교육을 시행합니다. [Source 1, Page 3]"]
        ),
    )
    streamed = StreamingAnswer("낙상 예방은?", [retrieved_chunk])

    assert list(streamed) == [
        "자료에서는 ",
        "낙상 예방 교육을 시행합니다. [Source 1, Page 3]",
    ]
    assert streamed.generated is not None
    assert streamed.generated.answer.endswith("[Source 1, Page 3]")
    assert len(streamed.generated.sources) == 1


def test_grounded_stream_returns_only_the_cited_candidate(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    second_chunk = RetrievedChunk(
        chunk_id=11,
        document_id=30,
        document_title="git.pdf",
        content="Git은 변경 이력을 추적한다.",
        page_start=9,
        page_end=9,
        score=0.8,
        source_refs={"page": 9},
    )
    monkeypatch.setattr(
        LLMClient,
        "stream_chat_completion",
        lambda self, messages, **kwargs: iter(
            ["Git은 변경 이력을 추적합니다. ", "[Source 2, Page 9]"]
        ),
    )
    streamed = StreamingAnswer("Git의 특성은?", [retrieved_chunk, second_chunk])

    list(streamed)

    assert streamed.generated is not None
    assert [source.chunk_id for source in streamed.generated.sources] == [11]


@pytest.mark.parametrize(
    "deltas",
    [
        ["[", "[NO_", "SOURCE", "]] 업로드된 자료에서 확인되지 않습니다."],
        ["[NO_SOURCE", "] 업로드된 자료에서 확인되지 않습니다."],
    ],
)
def test_no_source_marker_is_buffered_and_never_streamed(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
    deltas: list[str],
) -> None:
    monkeypatch.setattr(
        LLMClient,
        "stream_chat_completion",
        lambda self, messages, **kwargs: iter(deltas),
    )
    streamed = StreamingAnswer("자료 밖 질문", [retrieved_chunk])

    visible = "".join(streamed)

    assert visible == "업로드된 자료에서 확인되지 않습니다."
    assert "NO_SOURCE" not in visible
    assert streamed.generated is not None
    assert streamed.generated.sources == []


def test_empty_retrieval_streams_local_fallback_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        LLMClient,
        "stream_chat_completion",
        lambda *args, **kwargs: pytest.fail("LLM must not be called without chunks"),
    )
    streamed = StreamingAnswer("자료 밖 질문", [])

    visible = "".join(streamed)

    assert "자료" in visible
    assert streamed.generated is not None
    assert streamed.generated.sources == []


def test_insufficient_evidence_streams_clarification_without_revision(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    monkeypatch.setattr(
        LLMClient,
        "stream_chat_completion",
        lambda *args, **kwargs: pytest.fail("Insufficient evidence must not stream an LLM draft"),
    )
    streamed = StreamingAnswer(
        "rollback 중 꼬이면 어떻게 하나요?",
        [retrieved_chunk],
        evidence_matrix=EvidenceMatrix(
            status="insufficient",
            goals=(
                EvidenceMatrixGoal("g1", "현재 상태별 안전한 복구 절차", "missing"),
            ),
        ),
    )

    assert "".join(streamed) == INSUFFICIENT_EVIDENCE_ANSWER
    assert streamed.revision is None
    assert streamed.generated is not None
    assert streamed.generated.sources == []


def test_stream_exposes_final_citation_revision(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    monkeypatch.setattr(
        LLMClient,
        "stream_chat_completion",
        lambda self, messages, **kwargs: iter(["자료에서는 낙상 예방 교육을 시행합니다."]),
    )
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: (
            "자료에서는 낙상 예방 교육을 시행합니다. [Source 1, Page 3]"
        ),
    )
    streamed = StreamingAnswer("낙상 예방은?", [retrieved_chunk])

    assert "".join(streamed) == "자료에서는 낙상 예방 교육을 시행합니다."
    assert streamed.revision == (
        "자료에서는 낙상 예방 교육을 시행합니다. [Source 1, Page 3]"
    )
    assert streamed.generated is not None
    assert streamed.generated.answer == streamed.revision
    assert len(streamed.generated.sources) == 1


def test_stream_no_source_repair_keeps_grounded_subset(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    draft = (
        "자료에서는 낙상 예방 교육을 시행합니다. [Source 1, Page 3]\n"
        "근거가 없는 추가 절차도 반드시 수행해야 합니다."
    )
    monkeypatch.setattr(
        LLMClient,
        "stream_chat_completion",
        lambda self, messages, **kwargs: iter([draft]),
    )
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: (
            "[[NO_SOURCE]] 업로드된 자료에서 확인되지 않습니다."
        ),
    )
    streamed = StreamingAnswer("구체적인 예외 상황에서는 어떻게 하나요?", [retrieved_chunk])

    assert "근거가 없는 추가 절차" in "".join(streamed)
    assert streamed.revision is not None
    assert "낙상 예방 교육" in streamed.revision
    assert "근거가 없는 추가 절차" not in streamed.revision
    assert "구체적인 상황을 추가로 알려주세요" in streamed.revision
    assert streamed.generated is not None
    assert len(streamed.generated.sources) == 1
