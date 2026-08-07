import pytest

from app.clients.vllm_client import VLLMClient
from app.services.generator import generate_answer
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


def test_generate_answer_removes_sources_and_marker_for_ungrounded_response(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: "[[NO_SOURCE]] 업로드된 자료에서 확인되지 않습니다.",
    )

    generated = generate_answer("자료에 없는 질문", [retrieved_chunk])

    assert generated.answer == "업로드된 자료에서 확인되지 않습니다."
    assert generated.sources == []


def test_generate_answer_supports_legacy_no_source_prefix(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: "업로드된 자료에서 확인되지 않습니다. 질문을 바꿔주세요.",
    )

    generated = generate_answer("자료에 없는 질문", [retrieved_chunk])

    assert generated.sources == []


@pytest.mark.parametrize("marker", ["[[NO_SOURCE]", "[NO_SOURCE]", "[NO_SOURCE]]"])
def test_generate_answer_accepts_malformed_no_source_marker(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
    marker: str,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: (
            f"{marker} 업로드된 자료에서 OS의 메모리 관리정책에 대한 내용은 "
            "확인되지 않습니다."
        ),
    )

    generated = generate_answer("OS의 메모리 관리정책은?", [retrieved_chunk])

    assert generated.answer.startswith("업로드된 자료에서")
    assert "NO_SOURCE" not in generated.answer
    assert generated.sources == []


def test_generate_answer_keeps_generic_detail_after_no_source_marker(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: (
            "[[NO_SOURCE]] 업로드된 자료에서 확인되지 않습니다. "
            "관련 문서를 추가해 주세요."
        ),
    )

    generated = generate_answer("자료에 없는 배포 절차는?", [retrieved_chunk])

    assert "NO_SOURCE" not in generated.answer
    assert "관련 문서를 추가" in generated.answer
    assert generated.sources == []


def test_generate_answer_keeps_sources_for_grounded_response(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: (
            "자료에서는 낙상 예방 교육을 시행합니다. [Source 1, Page 3]"
        ),
    )

    generated = generate_answer("낙상 예방은?", [retrieved_chunk])

    assert generated.answer == "자료에서는 낙상 예방 교육을 시행합니다. [Source 1, Page 3]"
    assert len(generated.sources) == 1
    assert generated.sources[0].document_id == retrieved_chunk.document_id


def test_generate_answer_returns_only_cited_unique_source_pages(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    chunks = [
        retrieved_chunk,
        RetrievedChunk(
            chunk_id=11,
            document_id=30,
            document_title="git.pdf",
            content="Git은 변경 이력을 추적한다.",
            page_start=9,
            page_end=9,
            score=0.8,
            source_refs={"page": 9},
        ),
        RetrievedChunk(
            chunk_id=12,
            document_id=30,
            document_title="git.pdf",
            content="Git은 이전 버전으로 복구할 수 있다.",
            page_start=9,
            page_end=9,
            score=0.7,
            source_refs={"page": 9},
        ),
    ]
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: (
            "Git은 변경 이력을 추적합니다. "
            "[Source 2, Page 9; Source 3, Page 9; Source 99, Page 1]"
        ),
    )

    generated = generate_answer("Git의 특성은?", chunks)

    assert len(generated.sources) == 1
    assert generated.sources[0].document_id == 30
    assert generated.sources[0].page == 9
    assert generated.sources[0].chunk_id == 11


def test_generate_answer_keeps_all_sources_used_for_a_derived_conclusion(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    reset_chunk = RetrievedChunk(
        chunk_id=21,
        document_id=30,
        document_title="git-history.pdf",
        content="reset은 브랜치가 가리키는 커밋을 이동시켜 이후 이력을 변경한다.",
        page_start=10,
        page_end=10,
        score=0.9,
        source_refs={"page": 10},
    )
    revert_chunk = RetrievedChunk(
        chunk_id=22,
        document_id=30,
        document_title="git-history.pdf",
        content="revert는 기존 변경을 취소하는 새 커밋을 만들어 이전 이력을 보존한다.",
        page_start=11,
        page_end=11,
        score=0.8,
        source_refs={"page": 11},
    )
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: (
            "reset은 기존 이력을 변경하지만 revert는 취소 커밋을 추가해 이력을 보존하므로 "
            "공유 이력에는 revert가 적합합니다. "
            "[Source 2, Page 10; Source 3, Page 11]"
        ),
    )

    generated = generate_answer(
        "공유된 커밋에는 왜 revert를 사용하나요?",
        [retrieved_chunk, reset_chunk, revert_chunk],
    )

    assert [source.chunk_id for source in generated.sources] == [21, 22]


def test_generate_answer_does_not_expose_uncited_candidates(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: "자료에서는 낙상 예방 교육을 시행합니다.",
    )

    generated = generate_answer("낙상 예방은?", [retrieved_chunk])

    assert generated.sources == []


def test_generate_answer_blocks_exact_visual_page_request_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunk = RetrievedChunk(
        chunk_id=30,
        document_id=40,
        document_title="diagram.pdf",
        content="e1 e2 e4 e4 e3 e1",
        page_start=20,
        page_end=20,
        score=0.9,
        source_refs={
            "page_metadata": {
                "has_visual_content": True,
                "visual_evidence_risk": "visual_heavy",
            }
        },
    )
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: pytest.fail("Visual-only request must be blocked locally"),
    )

    generated = generate_answer(
        "20페이지 상태 다이어그램의 최종 값을 계산해 주세요.",
        [chunk],
    )

    assert "시각 근거가 검색되지 않았습니다" in generated.answer
    assert generated.sources == []


def test_generate_answer_retries_degenerate_repetition_once(
    monkeypatch: pytest.MonkeyPatch,
    retrieved_chunk: RetrievedChunk,
) -> None:
    responses = iter(
        [
            "낙상 예방은 t.t.t.t.t.t.t.t.t.t.t.t.t.t.t.t.t.t.t.t.",
            "자료에서는 낙상 예방 교육을 시행합니다. [Source 1, Page 3]",
        ]
    )
    operations: list[str] = []

    def complete(self, messages, **kwargs):
        operations.append(kwargs["operation"])
        return next(responses)

    monkeypatch.setattr(VLLMClient, "chat_completion", complete)

    generated = generate_answer("낙상 예방은?", [retrieved_chunk])

    assert operations == ["answer", "answer_retry"]
    assert "t.t.t" not in generated.answer
    assert len(generated.sources) == 1
