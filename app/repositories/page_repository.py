from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.page import DocumentPage
from app.repositories.chunk_repository import build_keyword_query
from app.services.pdf_parser import ParsedPage


def create_pages(db: Session, document_id: int, pages: list[ParsedPage]) -> list[DocumentPage]:
    rows = [
        DocumentPage(
            document_id=document_id,
            page_number=page.page_number,
            text=page.text,
            page_metadata=page.metadata,
        )
        for page in pages
    ]
    db.add_all(rows)
    db.flush()
    return rows


def delete_pages(db: Session, document_id: int) -> None:
    db.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))


def search_pages_by_keyword(
    db: Session,
    owner_id: int,
    query_text: str,
    limit: int,
) -> list[tuple[DocumentPage, float, str]]:
    document_vector = func.to_tsvector("simple", DocumentPage.text)
    query = build_keyword_query(query_text)
    rank = func.ts_rank_cd(document_vector, query).label("rank")
    rows = (
        db.query(DocumentPage, rank, Document.title)
        .join(Document, Document.id == DocumentPage.document_id)
        .filter(
            Document.owner_id == owner_id,
            Document.status == "indexed",
            Document.deleted_at.is_(None),
            DocumentPage.text.is_not(None),
            document_vector.op("@@")(query),
        )
        .order_by(rank.desc(), DocumentPage.id)
        .limit(limit)
        .all()
    )
    return [(page, float(score), title) for page, score, title in rows]


def search_pages_by_substring(
    db: Session,
    owner_id: int,
    query_text: str,
    limit: int,
) -> list[tuple[DocumentPage, float, str]]:
    similarity = func.greatest(
        func.similarity(DocumentPage.text, query_text),
        func.word_similarity(query_text, DocumentPage.text),
    ).label("similarity")
    rows = (
        db.query(DocumentPage, similarity, Document.title)
        .join(Document, Document.id == DocumentPage.document_id)
        .filter(
            Document.owner_id == owner_id,
            Document.status == "indexed",
            Document.deleted_at.is_(None),
            DocumentPage.text.is_not(None),
            similarity > 0,
        )
        .order_by(similarity.desc(), DocumentPage.id)
        .limit(limit)
        .all()
    )
    return [(page, float(score), title) for page, score, title in rows]
