from types import SimpleNamespace

import pytest

from app.services import hierarchical_retriever
from app.services.hierarchical_retriever import retrieve_hierarchical_chunks
from app.services.retrieval_trace import RetrievalTrace


def test_hierarchical_retrieval_fuses_pages_and_returns_overlapping_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """계층 검색이 페이지 결과를 융합해 겹치는 청크와 추적 기록을 반환하는지 보장한다."""
    relevant_page = SimpleNamespace(document_id=10, page_number=5)
    distractor_page = SimpleNamespace(document_id=10, page_number=2)
    relevant_chunk = SimpleNamespace(
        id=101,
        document_id=10,
        content="revert는 기존 이력을 보존한다.",
        page_start=5,
        page_end=5,
        source_refs={"page": 5},
    )
    monkeypatch.setattr(
        hierarchical_retriever.page_repository,
        "search_pages_by_keyword",
        lambda *args, **kwargs: [
            (relevant_page, 0.9, "git.pdf"),
            (distractor_page, 0.2, "git.pdf"),
        ],
    )
    monkeypatch.setattr(
        hierarchical_retriever.page_repository,
        "search_pages_by_substring",
        lambda *args, **kwargs: [(relevant_page, 0.8, "git.pdf")],
    )
    monkeypatch.setattr(
        hierarchical_retriever,
        "get_chunks_by_document_pages",
        lambda db, owner_id, locations: [(relevant_chunk, "git.pdf")],
    )
    monkeypatch.setattr(
        hierarchical_retriever,
        "rerank_rows",
        lambda question, rows, top_k, queries: rows[:top_k],
    )
    trace = RetrievalTrace(request_id="hierarchical-test")

    chunks = retrieve_hierarchical_chunks(
        db=object(),
        owner_id=7,
        question="왜 revert인가요?",
        queries=("revert 이력 보존", "DVCS 협업"),
        trace=trace,
    )

    assert [chunk.chunk_id for chunk in chunks] == [101]
    assert chunks[0].page_start == 5
    assert trace.retrieval_events[0]["stage"] == "hierarchical_fallback.pages"
    assert trace.retrieval_events[0]["pages"][0]["page"] == 5
    assert trace.retrieval_events[1]["stage"] == "hierarchical_fallback.chunks"
