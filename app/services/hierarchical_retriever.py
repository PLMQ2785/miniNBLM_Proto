from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.repositories import page_repository
from app.repositories.chunk_repository import get_chunks_by_document_pages
from app.services.reranker import rerank_rows
from app.services.retrieval_trace import RetrievalTrace
from app.services.retriever import RetrievedChunk


MAX_PAGE_CANDIDATES = 12
MAX_PAGE_RESULTS_PER_QUERY = 12
MAX_HIERARCHICAL_CHUNKS = 16
PAGE_ANCHORS_PER_QUERY = 2


def retrieve_hierarchical_chunks(
    db: Session,
    owner_id: int,
    question: str,
    queries: Sequence[str],
    *,
    document_id: int | None = None,
    trace: RetrievalTrace | None = None,
    trace_stage: str = "hierarchical_fallback",
) -> list[RetrievedChunk]:
    """선택 문서의 청크 검색이 부족할 때 페이지를 거쳐 겹치는 청크를 복구한다."""
    # 페이지를 먼저 찾은 뒤 그 페이지와 겹치는 청크를 복구한다.
    search_queries = _normalize_queries(question, queries)
    per_query_results = []
    for query in search_queries:
        keyword_rows = page_repository.search_pages_by_keyword(
            db,
            owner_id,
            query,
            MAX_PAGE_RESULTS_PER_QUERY,
            document_id=document_id,
        )
        substring_rows = page_repository.search_pages_by_substring(
            db,
            owner_id,
            query,
            MAX_PAGE_RESULTS_PER_QUERY,
            document_id=document_id,
        )
        per_query_results.append(
            _fuse_page_results(
                [keyword_rows, substring_rows],
                MAX_PAGE_RESULTS_PER_QUERY,
            )
        )

    # 넓은 RRF 결과가 좁은 쿼리의 핵심 페이지를 지우지 않게 앵커를 보존한다.
    pages = _merge_page_anchors(
        per_query_results,
        _fuse_page_results(per_query_results, MAX_PAGE_CANDIDATES),
        MAX_PAGE_CANDIDATES,
    )
    if trace is not None:
        trace.record_pages(stage=f"{trace_stage}.pages", pages=pages)
    if not pages:
        return []

    page_rank = {
        (page.document_id, page.page_number): rank
        for rank, (page, _, _) in enumerate(pages, start=1)
    }
    chunk_rows = get_chunks_by_document_pages(db, owner_id, set(page_rank))
    rows = [
        (chunk, _best_page_score(chunk, page_rank), title)
        for chunk, title in chunk_rows
    ]
    rows.sort(key=lambda row: (-row[1], row[0].id))
    rows = rerank_rows(
        question,
        rows,
        MAX_HIERARCHICAL_CHUNKS,
        queries=search_queries,
    )
    if trace is not None:
        trace.record_candidates(
            stage=f"{trace_stage}.chunks",
            query=question,
            algorithm="page_fts_trgm_rerank",
            rows=rows,
        )
    return [
        RetrievedChunk(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            document_title=title,
            content=chunk.content,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            score=score,
            source_refs=chunk.source_refs or {},
            content_type=getattr(chunk, "content_type", "text"),
        )
        for chunk, score, title in rows
    ]


def _normalize_queries(question: str, queries: Sequence[str]) -> list[str]:
    """계획 쿼리와 원 질문을 중복 없이 검색 상한에 맞춘다."""
    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in [*queries, question]:
        query = candidate.strip()
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        normalized.append(query)
    return normalized[:4]


def _fuse_page_results(result_sets, limit: int):
    """여러 페이지 검색 순위를 RRF 점수로 합친다."""
    pages_by_key = {}
    titles_by_key = {}
    scores: dict[tuple[int, int], float] = {}
    for rows in result_sets:
        for rank, (page, _, title) in enumerate(rows, start=1):
            key = (page.document_id, page.page_number)
            pages_by_key[key] = page
            titles_by_key[key] = title
            scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
    ranked_keys = sorted(scores, key=lambda key: (-scores[key], key))[:limit]
    return [
        (pages_by_key[key], scores[key], titles_by_key[key])
        for key in ranked_keys
    ]


def _merge_page_anchors(per_query_results, fused_results, limit: int):
    """각 쿼리의 상위 페이지를 먼저 보존하고 융합 결과로 채운다."""
    merged = []
    seen: set[tuple[int, int]] = set()
    for rows in per_query_results:
        for row in rows[:PAGE_ANCHORS_PER_QUERY]:
            page = row[0]
            key = (page.document_id, page.page_number)
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
            if len(merged) == limit:
                return merged
    for row in fused_results:
        page = row[0]
        key = (page.document_id, page.page_number)
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
        if len(merged) == limit:
            break
    return merged


def _best_page_score(chunk, page_rank: dict[tuple[int, int], int]) -> float:
    """청크와 겹치는 페이지 중 가장 높은 순위를 점수로 바꾼다."""
    if chunk.page_start is None:
        return 0.0
    end = chunk.page_end if chunk.page_end is not None else chunk.page_start
    ranks = [
        rank
        for (document_id, page), rank in page_rank.items()
        if document_id == chunk.document_id and chunk.page_start <= page <= end
    ]
    return 1.0 / (60 + min(ranks)) if ranks else 0.0
