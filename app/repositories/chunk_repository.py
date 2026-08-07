import re

from sqlalchemy import and_, delete, func, or_, tuple_
from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.models.document import Document
from app.services.chunker import TextChunk


MAX_KEYWORD_QUERY_TERMS = 32
KEYWORD_TERM_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


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


def get_chunks_by_document_indexes(
    db: Session,
    owner_id: int,
    locations: set[tuple[int, int]],
) -> list[tuple[Chunk, str]]:
    if not locations:
        return []
    return (
        db.query(Chunk, Document.title)
        .join(Document, Document.id == Chunk.document_id)
        .filter(
            Document.owner_id == owner_id,
            Document.status == "indexed",
            Document.deleted_at.is_(None),
            Chunk.deleted_at.is_(None),
            tuple_(Chunk.document_id, Chunk.chunk_index).in_(locations),
        )
        .order_by(Chunk.document_id, Chunk.chunk_index, Chunk.id)
        .all()
    )


def search_chunks_by_embedding(
    db: Session,
    owner_id: int,
    query_embedding: list[float],
    top_k: int,
) -> list[tuple[Chunk, float, str]]:
    distance = Chunk.embedding.cosine_distance(query_embedding).label("distance")
    rows = (
        db.query(Chunk, distance, Document.title)
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
    return [(chunk, float(score), title) for chunk, score, title in rows]


def search_chunks_by_keyword(
    db: Session,
    owner_id: int,
    question: str,
    top_k: int,
) -> list[tuple[Chunk, float, str]]:
    document_vector = func.to_tsvector("simple", Chunk.content)
    query = build_keyword_query(question)
    rank = func.ts_rank_cd(document_vector, query).label("rank")
    rows = (
        db.query(Chunk, rank, Document.title)
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
    return [(chunk, float(score), title) for chunk, score, title in rows]


def build_keyword_query(question: str):
    terms: list[str] = []
    seen: set[str] = set()
    for term in KEYWORD_TERM_PATTERN.findall(question):
        normalized = term.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        terms.append(term)
        if len(terms) == MAX_KEYWORD_QUERY_TERMS:
            break

    if not terms:
        return func.plainto_tsquery("simple", question)

    query = func.plainto_tsquery("simple", terms[0])
    for term in terms[1:]:
        query = query.op("||")(func.plainto_tsquery("simple", term))
    return query


def get_chunks_by_document_pages(
    db: Session,
    owner_id: int,
    locations: set[tuple[int, int]],
) -> list[tuple[Chunk, str]]:
    if not locations:
        return []
    page_conditions = [
        and_(
            Chunk.document_id == document_id,
            Chunk.page_start <= page_number,
            Chunk.page_end >= page_number,
        )
        for document_id, page_number in locations
    ]
    return (
        db.query(Chunk, Document.title)
        .join(Document, Document.id == Chunk.document_id)
        .filter(
            Document.owner_id == owner_id,
            Document.status == "indexed",
            Document.deleted_at.is_(None),
            Chunk.deleted_at.is_(None),
            or_(*page_conditions),
        )
        .order_by(Chunk.document_id, Chunk.chunk_index, Chunk.id)
        .all()
    )


def search_chunks_by_substring(
    db: Session,
    owner_id: int,
    question: str,
    top_k: int,
) -> list[tuple[Chunk, float, str]]:
    similarity = func.greatest(
        func.similarity(Chunk.content, question),
        func.word_similarity(question, Chunk.content),
    ).label("similarity")
    rows = (
        db.query(Chunk, similarity, Document.title)
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
    return [(chunk, float(score), title) for chunk, score, title in rows]
