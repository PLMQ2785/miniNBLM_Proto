from collections.abc import Sequence
from dataclasses import dataclass
import time

from sqlalchemy.orm import Session

from app.clients.embedding_client import EmbeddingClient
from app.observability import RETRIEVAL_DURATION, RETRIEVAL_REQUESTS
from app.repositories import retrieval_config_repository
from app.repositories.chunk_repository import (
    get_chunks_by_document_indexes,
    search_chunks_by_embedding,
    search_chunks_by_keyword,
    search_chunks_by_substring,
)
from app.search_algorithms import SearchAlgorithmKey
from app.services.reranker import rerank_rows
from app.services.retrieval_trace import RetrievalTrace
from app.services.query_rewriter import EvidenceGoal


ADJACENT_CHUNK_WINDOW = 1
MAX_ADJACENT_CHUNKS = 8
MAX_ADJACENT_CONTEXT_CHARS = 8_000
RERANK_CANDIDATE_MULTIPLIER = 3


@dataclass(frozen=True)
class RetrievedChunk:
    """검색부터 프롬프트·인용까지 공유하는 청크 표현이다."""
    chunk_id: int
    document_id: int
    document_title: str
    content: str
    page_start: int | None
    page_end: int | None
    score: float
    source_refs: dict
    content_type: str = "text"


def retrieve_chunks(
    db: Session,
    owner_id: int,
    question: str,
    top_k: int | None = None,
    queries: Sequence[str] | None = None,
    goals: Sequence[EvidenceGoal] | None = None,
    trace: RetrievalTrace | None = None,
    trace_stage: str = "initial",
) -> list[RetrievedChunk]:
    """활성 검색 설정으로 목표별 후보를 찾고 재순위화·인접 확장을 적용한다."""
    configuration = retrieval_config_repository.get_configuration(db)
    active_preset = retrieval_config_repository.get_preset(db, configuration.active_preset_key)
    if active_preset is None:
        raise RuntimeError("Active retrieval preset is missing")
    requested_limit = top_k if top_k is not None else active_preset.top_k
    algorithm = SearchAlgorithmKey(configuration.active_search_algorithm_key)
    goal_query_groups = _normalize_goal_query_groups(goals)
    # 다중 목표 질문은 목표마다 최소 한 결과가 들어갈 자리를 보장한다.
    result_limit = max(requested_limit, len(goal_query_groups))
    search_queries = _normalize_search_queries(
        question,
        (
            [question, *(query for _, group in goal_query_groups for query in group)]
            if goal_query_groups
            else queries
        ),
    )
    goal_ids_by_query: dict[str, list[str]] = {}
    for goal_id, group in goal_query_groups:
        for query in group:
            goal_ids = goal_ids_by_query.setdefault(query.casefold(), [])
            if goal_id not in goal_ids:
                goal_ids.append(goal_id)
    rerank_enabled = algorithm in {SearchAlgorithmKey.DENSE, SearchAlgorithmKey.HYBRID}
    # 의미 재순위화 전에 넉넉히 찾고 최종 상한만 프롬프트로 보낸다.
    final_candidate_limit = (
        result_limit * RERANK_CANDIDATE_MULTIPLIER if rerank_enabled else result_limit
    )
    started_at = time.perf_counter()
    try:
        if len(search_queries) == 1:
            rows = _search(
                db=db,
                owner_id=owner_id,
                question=search_queries[0],
                top_k=final_candidate_limit,
                algorithm=algorithm,
            )
            if trace is not None:
                trace.record_candidates(
                    stage=f"{trace_stage}.search",
                    query=search_queries[0],
                    algorithm=algorithm.value,
                    rows=rows,
                    goal_ids=tuple(
                        goal_ids_by_query.get(search_queries[0].casefold(), ())
                    ),
                )
        else:
            per_query_limit = max(result_limit * 2, final_candidate_limit)
            result_sets = [
                _search(
                    db=db,
                    owner_id=owner_id,
                    question=query,
                    top_k=per_query_limit,
                    algorithm=algorithm,
                )
                for query in search_queries
            ]
            if trace is not None:
                for query, query_rows in zip(search_queries, result_sets, strict=True):
                    trace.record_candidates(
                        stage=f"{trace_stage}.search",
                        query=query,
                        algorithm=algorithm.value,
                        rows=query_rows,
                        goal_ids=tuple(
                            goal_ids_by_query.get(query.casefold(), ())
                        ),
                    )
            # 쿼리별 앵커가 좁지만 필요한 목표를 RRF에서 잃지 않게 한다.
            fused_rows = _reciprocal_rank_fusion(result_sets, final_candidate_limit)
            rows = _merge_query_anchors(
                result_sets,
                fused_rows,
                final_candidate_limit,
            )
            if trace is not None:
                trace.record_candidates(
                    stage=f"{trace_stage}.fused",
                    query=None,
                    algorithm=algorithm.value,
                    rows=rows,
                )
        if rerank_enabled:
            rows = rerank_rows(
                question,
                rows,
                result_limit,
                queries=search_queries,
                goal_query_groups=goal_query_groups,
            )
            if trace is not None:
                trace.record_candidates(
                    stage=f"{trace_stage}.reranked",
                    query=question,
                    algorithm=algorithm.value,
                    rows=rows,
                    goal_ids=tuple(goal_id for goal_id, _ in goal_query_groups),
                )
        # 순위 앵커를 확정한 뒤에만 주변 문맥을 덧붙인다.
        rows = _expand_with_adjacent_chunks(db, owner_id, rows)
    except Exception:
        RETRIEVAL_REQUESTS.labels(algorithm=algorithm.value, status="error").inc()
        if trace is not None:
            trace.record_retrieval_error(
                stage=trace_stage,
                algorithm=algorithm.value,
                duration_seconds=time.perf_counter() - started_at,
            )
        raise
    else:
        status = "success" if rows else "empty"
        RETRIEVAL_REQUESTS.labels(algorithm=algorithm.value, status=status).inc()
        if trace is not None:
            trace.record_retrieval_complete(
                stage=trace_stage,
                algorithm=algorithm.value,
                queries=search_queries,
                rows=rows,
                duration_seconds=time.perf_counter() - started_at,
            )
    finally:
        RETRIEVAL_DURATION.labels(algorithm=algorithm.value).observe(
            time.perf_counter() - started_at
        )
    return [
        RetrievedChunk(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            document_title=document_title,
            content=chunk.content,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            score=score,
            source_refs=chunk.source_refs or {},
            content_type=getattr(chunk, "content_type", "text"),
        )
        for chunk, score, document_title in rows
    ]


def _normalize_search_queries(question: str, queries: Sequence[str] | None) -> list[str]:
    """검색 쿼리를 입력 순서대로 중복 제거하고 원 질문으로 폴백한다."""
    candidates = queries if queries is not None else (question,)
    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        query = candidate.strip()
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        normalized.append(query)
    return normalized or [question.strip()]


def _normalize_goal_query_groups(
    goals: Sequence[EvidenceGoal] | None,
) -> list[tuple[str, tuple[str, ...]]]:
    """근거 목표를 고유 ID와 정규화된 쿼리 묶음으로 바꾼다."""
    groups: list[tuple[str, tuple[str, ...]]] = []
    seen_ids: set[str] = set()
    for goal in goals or ():
        if goal.goal_id in seen_ids:
            raise ValueError(f"Duplicate evidence goal ID: {goal.goal_id}")
        queries = tuple(_normalize_search_queries(goal.description, goal.queries))
        if not queries:
            raise ValueError(f"Evidence goal has no search query: {goal.goal_id}")
        seen_ids.add(goal.goal_id)
        groups.append((goal.goal_id, queries))
    return groups


def _expand_with_adjacent_chunks(db: Session, owner_id: int, rows):
    """순위 후보 주변 청크를 개수·문자 예산 안에서 뒤에 덧붙인다."""
    if not rows:
        return rows

    seed_ids = {chunk.id for chunk, _, _ in rows}
    requested_locations: list[tuple[int, int, float]] = []
    locations: set[tuple[int, int]] = set()
    for chunk, score, _ in rows:
        for distance in range(1, ADJACENT_CHUNK_WINDOW + 1):
            for chunk_index in (chunk.chunk_index - distance, chunk.chunk_index + distance):
                if chunk_index < 0:
                    continue
                location = (chunk.document_id, chunk_index)
                if location in locations:
                    continue
                locations.add(location)
                requested_locations.append((*location, score))

    adjacent_by_location = {
        (chunk.document_id, chunk.chunk_index): (chunk, title)
        for chunk, title in get_chunks_by_document_indexes(db, owner_id, locations)
    }
    expanded_rows = list(rows)
    added_ids: set[int] = set()
    added_chars = 0
    for document_id, chunk_index, seed_score in requested_locations:
        adjacent = adjacent_by_location.get((document_id, chunk_index))
        if adjacent is None:
            continue
        chunk, document_title = adjacent
        if chunk.id in seed_ids or chunk.id in added_ids:
            continue
        if len(added_ids) >= MAX_ADJACENT_CHUNKS:
            break
        if added_chars + len(chunk.content) > MAX_ADJACENT_CONTEXT_CHARS:
            continue
        expanded_rows.append((chunk, seed_score, document_title))
        added_ids.add(chunk.id)
        added_chars += len(chunk.content)
    return expanded_rows


def _search(
    db: Session,
    owner_id: int,
    question: str,
    top_k: int,
    algorithm: SearchAlgorithmKey,
):
    """선택된 알고리즘으로 단일 쿼리 후보를 검색한다."""
    if algorithm == SearchAlgorithmKey.DENSE:
        return _dense_search(db, owner_id, question, top_k)
    if algorithm == SearchAlgorithmKey.KEYWORD:
        return search_chunks_by_keyword(db, owner_id, question, top_k)
    if algorithm == SearchAlgorithmKey.SUBSTRING:
        return search_chunks_by_substring(db, owner_id, question, top_k)
    if algorithm == SearchAlgorithmKey.HYBRID:
        candidate_limit = top_k * 3
        result_sets = (
            _dense_search(db, owner_id, question, candidate_limit),
            search_chunks_by_keyword(db, owner_id, question, candidate_limit),
            search_chunks_by_substring(db, owner_id, question, candidate_limit),
        )
        fused_rows = _reciprocal_rank_fusion(result_sets, top_k)
        return _merge_query_anchors(result_sets, fused_rows, top_k)
    raise RuntimeError(f"Unsupported search algorithm: {algorithm}")


def _dense_search(db: Session, owner_id: int, question: str, top_k: int):
    """질문 임베딩으로 소유자 범위의 유사 청크를 찾는다."""
    query_embedding = EmbeddingClient().embed_query(question)
    return search_chunks_by_embedding(
        db=db,
        owner_id=owner_id,
        query_embedding=query_embedding,
        top_k=top_k,
    )


def _reciprocal_rank_fusion(result_sets, top_k: int):
    """여러 검색 결과의 순위를 RRF 점수로 합친다."""
    chunks_by_id = {}
    titles_by_id = {}
    scores: dict[int, float] = {}
    for rows in result_sets:
        for rank, (chunk, _, document_title) in enumerate(rows, start=1):
            chunks_by_id[chunk.id] = chunk
            titles_by_id[chunk.id] = document_title
            scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (60 + rank)

    ranked_ids = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:top_k]
    return [
        (chunks_by_id[chunk_id], scores[chunk_id], titles_by_id[chunk_id])
        for chunk_id in ranked_ids
    ]


def _merge_query_anchors(result_sets, fused_rows, limit: int):
    """각 쿼리의 첫 후보를 보존한 뒤 융합 순위로 상한을 채운다."""
    merged_rows = []
    seen_ids: set[int] = set()
    for rows in result_sets:
        if not rows:
            continue
        anchor = rows[0]
        if anchor[0].id in seen_ids:
            continue
        seen_ids.add(anchor[0].id)
        merged_rows.append(anchor)
    for row in fused_rows:
        if len(merged_rows) == limit:
            break
        if row[0].id in seen_ids:
            continue
        seen_ids.add(row[0].id)
        merged_rows.append(row)
    return merged_rows[:limit]
