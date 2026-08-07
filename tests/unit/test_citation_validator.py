import pytest

from app.clients.vllm_client import VLLMClient
from app.services.citation_validator import (
    answer_needs_citation_repair,
    valid_cited_source_indexes,
    validate_answer_citations,
)
from app.services.retriever import RetrievedChunk


@pytest.fixture
def chunks() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=10,
            document_id=20,
            document_title="git.pdf",
            content="reset은 이후 이력을 삭제한다.",
            page_start=6,
            page_end=6,
            score=0.9,
            source_refs={"page": 6},
        ),
        RetrievedChunk(
            chunk_id=11,
            document_id=20,
            document_title="git.pdf",
            content="revert는 새 커밋을 만들어 기존 이력을 보존한다.",
            page_start=7,
            page_end=7,
            score=0.8,
            source_refs={"page": 7},
        ),
    ]


def test_complete_citations_skip_llm(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[RetrievedChunk],
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: pytest.fail("Citation repair must be skipped"),
    )
    answer = (
        "reset은 이후 이력을 삭제합니다. [Source 1, Page 6]\n"
        "revert는 기존 이력을 보존합니다. [Source 2, Page 7]"
    )

    assert validate_answer_citations("차이는?", answer, chunks) == answer
    assert answer_needs_citation_repair(answer, chunks) is False


def test_uncited_conclusion_is_repaired(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[RetrievedChunk],
) -> None:
    repaired = (
        "reset은 이후 이력을 삭제합니다. [Source 1, Page 6]\n"
        "revert는 기존 이력을 보존하므로 공유 이력에 더 적합합니다. "
        "[Source 1, Page 6; Source 2, Page 7]"
    )
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: repaired,
    )
    draft = (
        "reset은 이후 이력을 삭제합니다. [Source 1, Page 6]\n"
        "따라서 revert가 공유 이력에 더 적합합니다."
    )

    result = validate_answer_citations("왜 revert인가요?", draft, chunks)

    assert result == repaired
    assert valid_cited_source_indexes(result, chunks) == [0, 1]


def test_uncited_sentence_on_same_line_requires_repair(
    chunks: list[RetrievedChunk],
) -> None:
    answer = (
        "reset은 이후 이력을 삭제합니다. [Source 1, Page 6] "
        "따라서 공유 이력에는 revert가 더 적합합니다."
    )

    assert answer_needs_citation_repair(answer, chunks) is True


def test_wrong_page_triggers_repair(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[RetrievedChunk],
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: "reset은 이력을 삭제합니다. [Source 1, Page 6]",
    )

    result = validate_answer_citations(
        "reset은?",
        "reset은 이력을 삭제합니다. [Source 1, Page 99]",
        chunks,
    )

    assert result.endswith("[Source 1, Page 6]")


def test_parenthesized_source_is_not_treated_as_a_valid_citation(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[RetrievedChunk],
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: "reset은 이력을 삭제합니다. [Source 1, Page 6]",
    )

    result = validate_answer_citations(
        "reset은?",
        "reset은 이력을 삭제합니다. (Source 1, Page 6)",
        chunks,
    )

    assert result.endswith("[Source 1, Page 6]")


def test_invalid_repair_preserves_original_answer(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[RetrievedChunk],
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: "근거가 있다고 주장합니다. [Source 99, Page 1]",
    )
    draft = "revert가 적합합니다."

    assert validate_answer_citations("왜 revert인가요?", draft, chunks) == draft


def test_repair_can_reject_all_unsupported_claims(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[RetrievedChunk],
) -> None:
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: (
            "[[NO_SOURCE]] 업로드된 자료에서 확인되지 않습니다."
        ),
    )

    result = validate_answer_citations("자료 밖 질문", "근거 없는 답변입니다.", chunks)

    assert result.startswith("[[NO_SOURCE]]")
