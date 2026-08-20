from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document


def create_document(
    db: Session,
    owner_id: int,
    title: str,
    file_path: str,
    mime_type: str | None,
) -> Document:
    document = Document(
        owner_id=owner_id,
        title=title,
        file_path=file_path,
        mime_type=mime_type,
        status="uploaded",
    )
    db.add(document)
    db.flush()
    return document


def get_document_by_id(db: Session, document_id: int) -> Document | None:
    statement = select(Document).where(Document.id == document_id, Document.deleted_at.is_(None))
    return db.scalar(statement)


def get_document(
    db: Session,
    document_id: int,
    owner_id: int,
    *,
    for_update: bool = False,
) -> Document | None:
    # Ownership and soft-delete checks belong in the query, not only the router.
    statement = select(Document).where(
        Document.id == document_id,
        Document.owner_id == owner_id,
        Document.deleted_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def list_documents(db: Session, owner_id: int) -> list[Document]:
    statement = (
        select(Document)
        .where(Document.owner_id == owner_id, Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
    )
    return list(db.scalars(statement))


def list_all_documents(db: Session) -> list[Document]:
    statement = select(Document).where(Document.deleted_at.is_(None)).order_by(Document.id)
    return list(db.scalars(statement))


def list_interrupted_documents(db: Session) -> list[Document]:
    statement = (
        select(Document)
        .where(
            Document.deleted_at.is_(None),
            Document.status.in_(("uploaded", "processing")),
        )
        .order_by(Document.id)
        .with_for_update()
    )
    return list(db.scalars(statement))


def has_active_documents(db: Session) -> bool:
    statement = select(Document.id).where(
        Document.deleted_at.is_(None),
        Document.status.in_(("uploaded", "processing")),
    ).limit(1)
    return db.scalar(statement) is not None


def update_file_path(db: Session, document: Document, file_path: str) -> Document:
    document.file_path = file_path
    document.updated_at = datetime.now(UTC)
    db.flush()
    return document


def update_status(
    db: Session,
    document: Document,
    status: str,
    error_message: str | None = None,
) -> Document:
    document.status = status
    document.error_message = error_message
    document.updated_at = datetime.now(UTC)
    db.flush()
    return document


def update_index_metadata(
    db: Session,
    document: Document,
    preset_key: str,
    index_version: int,
) -> Document:
    document.indexed_preset_key = preset_key
    document.index_version = index_version
    db.flush()
    return document


def delete_document(db: Session, document: Document) -> None:
    db.delete(document)
    db.flush()
