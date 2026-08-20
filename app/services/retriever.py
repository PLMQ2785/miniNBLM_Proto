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
    configuration = retrieval_config_repository.get_configuration(db)
    active_preset = retrieval_config_repository.get_preset(db, configuration.active_preset_key)
    if active_preset is None:
        raise RuntimeError("Active retrieval preset is missing")
    requested_limit = top_k if top_k is not None else active_preset.top_k
    algorithm = SearchAlgorithmKey(configuration.active_search_algorithm_key)
    goal_query_groups = _normalize_goal_query_groups(goals)
    # A multi-goal question must keep room for at least one result per goal.
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
    # Over-fetch before semantic reranking; only the final limit reaches the prompt.
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
            # Query anchors stop RRF from erasing a narrow but necessary facet.
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
        # Add local continuity only after the ranked anchors are fixed.
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
    query_embedding = EmbeddingClient().embed_query(question)
    return search_chunks_by_embedding(
        db=db,
        owner_id=owner_id,
        query_embedding=query_embedding,
        top_k=top_k,
    )


def _reciprocal_rank_fusion(result_sets, top_k: int):
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
