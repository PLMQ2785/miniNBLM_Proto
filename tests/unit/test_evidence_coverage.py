import pytest

from app.clients.vllm_client import VLLMClient
from app.services import evidence_coverage
from app.services.evidence_coverage import (
    assess_evidence_coverage,
    complete_evidence_coverage,
)
from app.services.retriever import RetrievedChunk


def _chunk(chunk_id: int, content: str, page: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=10,
        document_title="git.pdf",
        content=content,
        page_start=page,
        page_end=page,
        score=0.9,
        source_refs={"page": page},
    )


def test_coverage_assessment_parses_missing_facets_and_retry_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: (
            "STATUS: INSUFFICIENT\n"
            "MISSING: 2\n"
            "RETRY 2: DVCS 공유 이력 재작성 협업 충돌"
        ),
    )

    assessment = assess_evidence_coverage(
        "왜 revert를 사용하나요?",
        ("reset 이력 변경", "DVCS 협업 영향"),
        [_chunk(1, "reset은 이력을 변경한다.", 10)],
    )

    assert assessment is not None
    assert assessment.sufficient is False
    assert assessment.missing_queries == ("DVCS 협업 영향",)
    assert assessment.retry_queries == ("DVCS 공유 이력 재작성 협업 충돌",)


def test_coverage_assessment_accepts_markdown_formatting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: (
            "```text\n"
            "- **STATUS: INSUFFICIENT**\n"
            "- **MISSING: 2**\n"
            "- **RETRY 2:** git revert shared history\n"
            "```"
        ),
    )

    assessment = assess_evidence_coverage(
        "왜 revert를 사용하나요?",
        ("reset semantics", "collaboration history"),
        [_chunk(1, "reset은 이력을 변경한다.", 10)],
    )

    assert assessment is not None
    assert assessment.missing_queries == ("collaboration history",)
    assert assessment.retry_queries == ("git revert shared history",)


def test_coverage_assessment_treats_malformed_mixed_status_as_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: (
            "STATUS: SUFFICE_INSUFFICIENT\n"
            "MISSING: 1\n"
            "RETRY 1: git reset vs git revert"
        ),
    )

    assessment = assess_evidence_coverage(
        "왜 revert를 사용하나요?",
        ("reset과 revert 비교",),
        [_chunk(1, "부분 근거", 10)],
    )

    assert assessment is not None
    assert assessment.sufficient is False
    assert assessment.retry_queries == ("git reset vs git revert",)


def test_coverage_retry_merges_recovered_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            "STATUS: INSUFFICIENT\nMISSING: 2\nRETRY 2: DVCS 공유 이력 충돌",
            "STATUS: SUFFICIENT",
        ]
    )
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: next(responses),
    )
    initial = _chunk(1, "revert는 이력을 보존한다.", 6)
    supplemental = _chunk(2, "공유 이력을 재작성하면 협업자 이력과 충돌한다.", 19)
    retry_call = {}

    def retry(**kwargs):
        retry_call.update(kwargs)
        return [supplemental]

    monkeypatch.setattr(evidence_coverage, "retrieve_chunks", retry)

    chunks = complete_evidence_coverage(
        db=object(),
        owner_id=7,
        question="push 후 왜 revert를 사용하나요?",
        queries=("전체 질문", "revert 이력 보존", "DVCS 협업 영향"),
        chunks=[initial],
    )

    assert [chunk.chunk_id for chunk in chunks] == [2, 1]
    assert retry_call["owner_id"] == 7
    assert retry_call["queries"] == ("DVCS 공유 이력 충돌",)


def test_coverage_retry_preserves_merged_context_when_judge_remains_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: "STATUS: INSUFFICIENT\nMISSING: 1\nRETRY 1: missing",
    )
    monkeypatch.setattr(
        evidence_coverage,
        "retrieve_chunks",
        lambda **kwargs: [_chunk(2, "여전히 관련 없는 근거", 20)],
    )
    monkeypatch.setattr(
        evidence_coverage,
        "retrieve_hierarchical_chunks",
        lambda **kwargs: [],
    )

    chunks = complete_evidence_coverage(
        db=object(),
        owner_id=7,
        question="질문",
        queries=("전체 질문", "필수 근거"),
        chunks=[_chunk(1, "부분 근거", 6)],
    )

    assert [chunk.chunk_id for chunk in chunks] == [2, 1]


def test_empty_retry_preserves_initial_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: (
            "STATUS: INSUFFICIENT\nMISSING: 1\nRETRY 1: missing evidence"
        ),
    )
    monkeypatch.setattr(evidence_coverage, "retrieve_chunks", lambda **kwargs: [])
    monkeypatch.setattr(
        evidence_coverage,
        "retrieve_hierarchical_chunks",
        lambda **kwargs: [],
    )
    initial = _chunk(1, "부분적으로 유효한 최초 근거", 6)

    chunks = complete_evidence_coverage(
        db=object(),
        owner_id=7,
        question="질문",
        queries=("전체 질문", "필수 근거"),
        chunks=[initial],
    )

    assert chunks == [initial]


def test_empty_initial_context_uses_hierarchical_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovered = _chunk(3, "계층 검색으로 찾은 근거", 9)
    monkeypatch.setattr(
        evidence_coverage,
        "retrieve_hierarchical_chunks",
        lambda **kwargs: [recovered],
    )
    monkeypatch.setattr(
        evidence_coverage,
        "retrieve_chunks",
        lambda **kwargs: pytest.fail("Targeted retry is unnecessary after sufficient fallback"),
    )
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: "STATUS: SUFFICIENT",
    )

    chunks = complete_evidence_coverage(
        db=object(),
        owner_id=7,
        question="질문",
        queries=("질문",),
        chunks=[],
    )

    assert chunks == [recovered]


def test_unresolved_evidence_uses_exactly_two_retrieval_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: "STATUS: INSUFFICIENT\nMISSING: 1\nRETRY 1: missing",
    )

    def targeted(**kwargs):
        calls.append("targeted")
        return [_chunk(2, "표적 검색 근거", 7)]

    def hierarchical(**kwargs):
        calls.append("hierarchical")
        return [_chunk(3, "페이지 fallback 근거", 8)]

    monkeypatch.setattr(evidence_coverage, "retrieve_chunks", targeted)
    monkeypatch.setattr(
        evidence_coverage,
        "retrieve_hierarchical_chunks",
        hierarchical,
    )

    chunks = complete_evidence_coverage(
        db=object(),
        owner_id=7,
        question="질문",
        queries=("질문",),
        chunks=[_chunk(1, "최초 근거", 6)],
    )

    assert calls == ["targeted", "hierarchical"]
    assert [chunk.chunk_id for chunk in chunks] == [3, 2, 1]


def test_coverage_failure_preserves_initial_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = _chunk(1, "근거", 1)

    def fail(*args, **kwargs):
        raise RuntimeError("vLLM unavailable")

    monkeypatch.setattr(VLLMClient, "chat_completion", fail)
    monkeypatch.setattr(
        evidence_coverage,
        "retrieve_chunks",
        lambda **kwargs: pytest.fail("Retry must not run when the coverage check fails"),
    )

    chunks = complete_evidence_coverage(
        db=object(),
        owner_id=7,
        question="질문",
        queries=("질문",),
        chunks=[initial],
    )

    assert chunks == [initial]
