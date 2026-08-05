from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.page import DocumentPage
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
