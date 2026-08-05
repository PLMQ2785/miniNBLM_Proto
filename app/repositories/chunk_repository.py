from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.models.document import Document
from app.services.chunker import TextChunk


def create_chunks(
    db: Session,
    document_id: int,
    chunks: list[TextChunk],
    embeddings: list[list[float]],
) -> list[Chunk]:
    rows = [
        Chunk(
            document_id=document_id,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            embedding=embedding,
            source_refs=chunk.source_refs,
            chunk_metadata=chunk.metadata,
        )
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]
    db.add_all(rows)
    db.flush()
    return rows


def delete_chunks(db: Session, document_id: int) -> None:
    db.execute(delete(Chunk).where(Chunk.document_id == document_id))


def search_chunks_by_embedding(
    db: Session,
    owner_id: int,
    query_embedding: list[float],
    top_k: int,
) -> list[tuple[Chunk, float]]:
    distance = Chunk.embedding.cosine_distance(query_embedding).label("distance")
    rows = (
        db.query(Chunk, distance)
        .join(Document, Document.id == Chunk.document_id)
        .filter(
            Document.owner_id == owner_id,
            Document.status == "indexed",
            Document.deleted_at.is_(None),
            Chunk.deleted_at.is_(None),
            Chunk.embedding.is_not(None),
        )
        .order_by(distance)
        .limit(top_k)
        .all()
    )
    return [(chunk, float(score)) for chunk, score in rows]


def search_chunks_by_keyword(
    db: Session,
    owner_id: int,
    question: str,
    top_k: int,
) -> list[tuple[Chunk, float]]:
    document_vector = func.to_tsvector("simple", Chunk.content)
    query = func.plainto_tsquery("simple", question)
    rank = func.ts_rank_cd(document_vector, query).label("rank")
    rows = (
        db.query(Chunk, rank)
        .join(Document, Document.id == Chunk.document_id)
        .filter(
            Document.owner_id == owner_id,
            Document.status == "indexed",
            Document.deleted_at.is_(None),
            Chunk.deleted_at.is_(None),
            document_vector.op("@@")(query),
        )
        .order_by(rank.desc(), Chunk.id)
        .limit(top_k)
        .all()
    )
    return [(chunk, float(score)) for chunk, score in rows]


def search_chunks_by_substring(
    db: Session,
    owner_id: int,
    question: str,
    top_k: int,
) -> list[tuple[Chunk, float]]:
    similarity = func.greatest(
        func.similarity(Chunk.content, question),
        func.word_similarity(question, Chunk.content),
    ).label("similarity")
    rows = (
        db.query(Chunk, similarity)
        .join(Document, Document.id == Chunk.document_id)
        .filter(
            Document.owner_id == owner_id,
            Document.status == "indexed",
            Document.deleted_at.is_(None),
            Chunk.deleted_at.is_(None),
            similarity > 0,
        )
        .order_by(similarity.desc(), Chunk.id)
        .limit(top_k)
        .all()
    )
    return [(chunk, float(score)) for chunk, score in rows]
