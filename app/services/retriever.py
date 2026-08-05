from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.clients.embedding_client import EmbeddingClient
from app.repositories import retrieval_config_repository
from app.repositories.chunk_repository import (
    search_chunks_by_embedding,
    search_chunks_by_keyword,
    search_chunks_by_substring,
)
from app.search_algorithms import SearchAlgorithmKey


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


def retrieve_chunks(
    db: Session,
    owner_id: int,
    question: str,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    configuration = retrieval_config_repository.get_configuration(db)
    active_preset = retrieval_config_repository.get_preset(db, configuration.active_preset_key)
    if active_preset is None:
        raise RuntimeError("Active retrieval preset is missing")
    result_limit = top_k if top_k is not None else active_preset.top_k
    algorithm = SearchAlgorithmKey(configuration.active_search_algorithm_key)
    rows = _search(
        db=db,
        owner_id=owner_id,
        question=question,
        top_k=result_limit,
        algorithm=algorithm,
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
        )
        for chunk, score, document_title in rows
    ]


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
        return _reciprocal_rank_fusion(
            (
                _dense_search(db, owner_id, question, candidate_limit),
                search_chunks_by_keyword(db, owner_id, question, candidate_limit),
                search_chunks_by_substring(db, owner_id, question, candidate_limit),
            ),
            top_k,
        )
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
