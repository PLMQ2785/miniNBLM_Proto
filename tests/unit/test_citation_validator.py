import pytest

from app.clients.llm_client import LLMClient
from app.services.citation_validator import (
    answer_needs_citation_repair,
    valid_cited_source_indexes,
    validate_answer_citations,
)
from app.services.retriever import RetrievedChunk


@pytest.fixture
def chunks() -> list[RetrievedChunk]:
    """인용 검증에 쓸 서로 다른 페이지의 검색 청크를 제공한다."""
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
    """완전한 인용은 LLM 복구 없이 그대로 통과하는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: pytest.fail("Citation repair must be skipped"),
    )
    answer = (
        "reset은 이후 이력을 삭제합니다. [Source 1, Page 6]\n"
        "revert는 기존 이력을 보존합니다. [Source 2, Page 7]"
    )

    assert validate_answer_citations("차이는?", answer, chunks) == answer
    assert answer_needs_citation_repair(answer, chunks) is False


def test_complete_citations_remove_revised_answer_heading_without_llm(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[RetrievedChunk],
) -> None:
    """완전한 인용의 수정 답변 머리말을 LLM 없이 제거하는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: pytest.fail("Citation repair must be skipped"),
    )

    result = validate_answer_citations(
        "reset은?",
        "### [Revised answer]\nreset은 이후 이력을 삭제합니다. [Source 1, Page 6]",
        chunks,
    )

    assert result == "reset은 이후 이력을 삭제합니다. [Source 1, Page 6]"


def test_bare_source_reference_is_completed_from_chunk_page(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[RetrievedChunk],
) -> None:
    """페이지 없는 출처 표기를 청크 페이지로 로컬 보완하는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: pytest.fail("Structural normalization needs no LLM"),
    )

    result = validate_answer_citations(
        "reset은?",
        "reset은 대상 이후 이력을 삭제합니다. [Source 1]",
        chunks,
    )

    assert result.endswith("[Source 1, Page 6]")


def test_uncited_conclusion_is_repaired(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[RetrievedChunk],
) -> None:
    """인용 없는 결론을 양쪽 근거가 달린 답변으로 복구하는지 보장한다."""
    repaired = (
        "reset은 이후 이력을 삭제합니다. [Source 1, Page 6]\n"
        "revert는 기존 이력을 보존하므로 공유 이력에 더 적합합니다. "
        "[Source 1, Page 6; Source 2, Page 7]"
    )
    monkeypatch.setattr(
        LLMClient,
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
    """같은 줄의 인용 없는 후속 문장도 복구 대상으로 판정하는지 보장한다."""
    answer = (
        "reset은 이후 이력을 삭제합니다. [Source 1, Page 6] "
        "따라서 공유 이력에는 revert가 더 적합합니다."
    )

    assert answer_needs_citation_repair(answer, chunks) is True


def test_wrong_page_triggers_repair(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[RetrievedChunk],
) -> None:
    """잘못된 페이지를 실제 출처 페이지로 로컬 교정하는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: pytest.fail("Known source pages need no LLM repair"),
    )

    result = validate_answer_citations(
        "reset은?",
        "reset은 이력을 삭제합니다. [Source 1, Page 99]",
        chunks,
    )

    assert result.endswith("[Source 1, Page 6]")


def test_grouped_citation_pages_are_normalized_from_source_chunks(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[RetrievedChunk],
) -> None:
    """묶음 인용의 각 페이지를 대응 청크 기준으로 정규화하는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: pytest.fail("Known source pages need no LLM repair"),
    )

    result = validate_answer_citations(
        "차이는?",
        (
            "reset과 revert는 이력 처리 방식이 다릅니다. "
            "[Source 1, Page 99; Source 2, Page 98]"
        ),
        chunks,
    )

    assert result.endswith("[Source 1, Page 6; Source 2, Page 7]")


def test_malformed_source_number_list_is_not_a_valid_citation(
    chunks: list[RetrievedChunk],
) -> None:
    """구조가 깨진 출처 번호 목록을 유효 인용으로 인정하지 않는지 보장한다."""
    answer = "관련 자료입니다. [Source 1, Page 6, 2, 5, 7]"

    assert answer_needs_citation_repair(answer, chunks) is True


def test_parenthesized_source_is_not_treated_as_a_valid_citation(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[RetrievedChunk],
) -> None:
    """괄호형 출처 표기를 유효 인용으로 오인하지 않고 복구하는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
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
    """복구 결과의 출처도 유효하지 않으면 원 답변을 보존하는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: "근거가 있다고 주장합니다. [Source 99, Page 1]",
    )
    draft = "revert가 적합합니다."

    assert validate_answer_citations("왜 revert인가요?", draft, chunks) == draft


def test_repair_can_reject_all_unsupported_claims(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[RetrievedChunk],
) -> None:
    """뒷받침할 수 없는 주장은 모두 근거 없음으로 거부할 수 있는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: (
            "[[NO_SOURCE]] 업로드된 자료에서 확인되지 않습니다."
        ),
    )

    result = validate_answer_citations("자료 밖 질문", "근거 없는 답변입니다.", chunks)

    assert result.startswith("[[NO_SOURCE]]")


def test_no_source_repair_preserves_only_validly_cited_claims(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[RetrievedChunk],
) -> None:
    """근거 없음 복구에서도 유효 인용 문장만 남기고 unsupported 주장을 제거하는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: (
            "[[NO_SOURCE]] 업로드된 자료에서 확인되지 않습니다."
        ),
    )
    draft = (
        "reset은 이후 이력을 삭제합니다. [Source 1, Page 6]\n"
        "문제가 생기면 reflog로 임의 복구하면 됩니다."
    )

    result = validate_answer_citations(
        "commit rollback 중 꼬이면 어떻게 하나요?",
        draft,
        chunks,
    )

    assert "reset은 이후 이력을 삭제" in result
    assert "[Source 1, Page 6]" in result
    assert "reflog" not in result
    assert "구체적인 상황을 추가로 알려주세요" in result
    assert not result.startswith("[[NO_SOURCE]]")


def test_repair_removes_bracketed_revised_answer_heading(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[RetrievedChunk],
) -> None:
    """복구 답변에 붙은 대괄호형 머리말을 최종 결과에서 제거하는지 보장한다."""
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: (
            "### [Revised answer]\nreset은 이후 이력을 삭제합니다. [Source 1, Page 6]"
        ),
    )

    result = validate_answer_citations("reset은?", "reset은 이력을 삭제합니다.", chunks)

    assert not result.startswith("[Revised answer]")
    assert result.endswith("[Source 1, Page 6]")
