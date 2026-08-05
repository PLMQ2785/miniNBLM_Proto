import logging
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models.document import Document
from app.repositories import document_repository
from app.storage.local_storage import LocalStorage
from app.services.upload_validation import validate_saved_pdf


class DocumentNotFoundError(Exception):
    pass


class DocumentDeleteConflictError(Exception):
    pass


logger = logging.getLogger(__name__)
ACTIVE_DOCUMENT_STATUSES = {"uploaded", "processing"}


async def create_document_from_upload(db: Session, owner_id: int, file: UploadFile) -> Document:
    title = Path((file.filename or "uploaded.pdf").replace("\\", "/")).name or "uploaded.pdf"
    document = document_repository.create_document(
        db=db,
        owner_id=owner_id,
        title=title,
        file_path="",
        mime_type=file.content_type,
    )
    db.commit()
    db.refresh(document)

    storage = LocalStorage()
    try:
        file_path = await storage.save_upload_file(file, document.id)
        validate_saved_pdf(file_path)
    except Exception:
        document_repository.delete_document(db, document)
        db.commit()
        try:
            storage.delete_document(document.id)
        except OSError:
            logger.exception("Failed to clean rejected upload for document_id=%s", document.id)
        raise

    document = document_repository.update_file_path(db, document, file_path)
    db.commit()
    db.refresh(document)
    return document


def get_document(
    db: Session,
    document_id: int,
    owner_id: int,
    *,
    for_update: bool = False,
) -> Document:
    document = document_repository.get_document(db, document_id, owner_id, for_update=for_update)
    if document is None:
        raise DocumentNotFoundError
    return document


def list_documents(db: Session, owner_id: int) -> list[Document]:
    return document_repository.list_documents(db, owner_id)


def delete_document(db: Session, document_id: int, owner_id: int) -> None:
    document = get_document(db, document_id, owner_id, for_update=True)
    if document.status in ACTIVE_DOCUMENT_STATUSES:
        raise DocumentDeleteConflictError

    document_repository.delete_document(db, document)
    db.commit()

    try:
        LocalStorage().delete_document(document_id)
    except OSError:
        logger.exception("Failed to remove files for deleted document_id=%s", document_id)
