import pytest

from app.clients.llm_client import ContextLengthExceededError, LLMClient
from app.services.evidence_coverage import EvidenceMatrix, EvidenceMatrixGoal
from app.services.generator import INSUFFICIENT_EVIDENCE_ANSWER, StreamingAnswer
from app.services.retriever import RetrievedChunk


@pytest.fixture
def retrieved_chunk() -> RetrievedChunk:
    """스트리밍 답변 검증에 쓸 기본 검색 청크를 제공한다."""
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
    """근거 있는 응답 조각을 그대로 흘리고 최종 출처를 유지하는지 보장한다."""
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
    """스트림의 최종 출처에 실제 인용된 후보만 포함하는지 보장한다."""
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
    """조각난 근거 없음 표식을 버퍼링해 사용자에게 노출하지 않는지 보장한다."""
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
    """검색 결과가 없으면 LLM 없이 로컬 안내를 스트리밍하는지 보장한다."""
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
    """근거 부족이면 수정 단계 없이 구체화 안내를 스트리밍하는지 보장한다."""
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
    """스트림 초안과 달라진 최종 인용 수정본을 별도로 노출하는지 보장한다."""
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
    """근거 없음 복구가 초안의 유효 인용 문장만 보존하는지 보장한다."""
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


def test_stream_retries_with_compact_context_before_first_visible_delta(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """첫 델타 전 입력 초과는 축소 프롬프트로 재시도해 정상 스트림을 연다."""
    calls = 0

    def stream(self, messages, **kwargs):
        """첫 단계는 거부하고 축소 단계에서는 근거 답변을 반환한다."""
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ContextLengthExceededError("context overflow")
        yield "낙상 예방 교육 내용입니다. [Source 1, Page 3]"

    monkeypatch.setattr(LLMClient, "stream_chat_completion", stream)
    streamed = StreamingAnswer("낙상 예방은?", [retrieved_chunk])

    visible = "".join(streamed)

    assert calls == 2
    assert visible.endswith("[Source 1, Page 3]")
    assert streamed.revision is None
    assert streamed.generated is not None
    assert [source.chunk_id for source in streamed.generated.sources] == [10]


def test_stream_replaces_partial_answer_after_context_overflow(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """일부 델타 뒤 입력 초과가 나면 재생성 결과를 revision으로 전체 교체한다."""
    calls = 0

    def stream(self, messages, **kwargs):
        """첫 단계는 일부만 보낸 뒤 실패하고 축소 단계는 완전한 답을 반환한다."""
        nonlocal calls
        calls += 1
        if calls == 1:
            yield "불완전한 답변"
            raise ContextLengthExceededError("context overflow")
        yield "낙상 예방 교육 내용입니다. [Source 1, Page 3]"

    monkeypatch.setattr(LLMClient, "stream_chat_completion", stream)
    streamed = StreamingAnswer("낙상 예방은?", [retrieved_chunk])

    assert "".join(streamed) == "불완전한 답변"
    assert calls == 2
    assert streamed.revision == "낙상 예방 교육 내용입니다. [Source 1, Page 3]"
    assert streamed.generated is not None
    assert streamed.generated.answer == streamed.revision


def test_stream_returns_extractive_evidence_when_every_attempt_overflows(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    """모든 스트림 단계가 초과해도 오류 대신 근거 발췌와 출처를 완료한다."""
    calls = 0

    def overflow(self, messages, **kwargs):
        """모든 생성 단계에서 컨텍스트 초과를 반환한다."""
        nonlocal calls
        calls += 1
        raise ContextLengthExceededError("context overflow")
        yield ""

    monkeypatch.setattr(LLMClient, "stream_chat_completion", overflow)
    streamed = StreamingAnswer("낙상 예방은?", [retrieved_chunk])

    visible = "".join(streamed)

    assert calls == 3
    assert "검색된 핵심 근거" in visible
    assert "[Source 1, Page 3]" in visible
    assert streamed.revision is None
    assert streamed.generated is not None
    assert [source.chunk_id for source in streamed.generated.sources] == [10]
