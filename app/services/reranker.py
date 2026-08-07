import logging
from math import sqrt
import time

from app.clients.embedding_client import EmbeddingClient
from app.observability import RERANK_DURATION, RERANK_REQUESTS


logger = logging.getLogger(__name__)

SEMANTIC_WEIGHT = 0.8
RETRIEVAL_RANK_WEIGHT = 0.2
ORIGINAL_QUERY_SHARE = 0.7
FACET_QUERY_SHARE = 0.3


def rerank_rows(question: str, rows, top_k: int, queries=None):
    if not rows:
        RERANK_REQUESTS.labels(status="empty").inc()
        return []

    started_at = time.perf_counter()
    try:
        rerank_queries = _normalize_rerank_queries(question, queries)
        query_embeddings = EmbeddingClient().embed_queries(rerank_queries)
        reranked = _rerank_with_embeddings(query_embeddings, rows, top_k)
    except Exception:
        logger.warning("Semantic reranking failed; preserving retrieval rank", exc_info=True)
        RERANK_REQUESTS.labels(status="fallback").inc()
        return list(rows[:top_k])
    else:
        RERANK_REQUESTS.labels(status="success").inc()
        return reranked
    finally:
        RERANK_DURATION.observe(time.perf_counter() - started_at)


def _normalize_rerank_queries(question: str, queries) -> list[str]:
    normalized = [question.strip()]
    seen = {question.strip().casefold()}
    for candidate in queries or ():
        query = candidate.strip()
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        normalized.append(query)
    return normalized


def _rerank_with_embeddings(query_embeddings: list[list[float]], rows, top_k: int):
    if not query_embeddings:
        raise ValueError("At least one query embedding is required")
    row_count = len(rows)
    scored_rows = []
    for rank, (chunk, _, document_title) in enumerate(rows, start=1):
        query_scores = [
            max(0.0, _cosine_similarity(query_embedding, chunk.embedding))
            for query_embedding in query_embeddings
        ]
        if len(query_scores) == 1:
            semantic_score = query_scores[0]
        else:
            semantic_score = (
                ORIGINAL_QUERY_SHARE * query_scores[0]
                + FACET_QUERY_SHARE * max(query_scores[1:])
            )
        rank_score = 1.0 if row_count == 1 else 1.0 - (rank - 1) / (row_count - 1)
        combined_score = float(
            SEMANTIC_WEIGHT * semantic_score + RETRIEVAL_RANK_WEIGHT * rank_score
        )
        scored_rows.append((chunk, combined_score, document_title, rank, query_scores))

    scored_rows.sort(key=lambda row: (-row[1], row[3], row[0].id))
    selected_ids: set[int] = set()
    if len(query_embeddings) > 1:
        for query_index in range(1, len(query_embeddings)):
            best_for_query = max(
                scored_rows,
                key=lambda row: (row[4][query_index], -row[3], -row[0].id),
            )
            selected_ids.add(best_for_query[0].id)
            if len(selected_ids) == top_k:
                break
    for row in scored_rows:
        if len(selected_ids) == top_k:
            break
        selected_ids.add(row[0].id)

    return [
        (chunk, score, document_title)
        for chunk, score, document_title, _, _ in scored_rows
        if chunk.id in selected_ids
    ]


def _cosine_similarity(left: list[float], right) -> float:
    if right is None or len(left) != len(right) or not left:
        return 0.0
    dot_product = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return float(dot_product / (left_norm * right_norm))
