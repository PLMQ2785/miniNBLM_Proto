import logging
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models.document import Document
from app.repositories import document_repository
from app.storage.local_storage import LocalStorage
from app.services.upload_validation import validate_saved_pdf


class DocumentNotFoundError(Exception):
    """사용자 소유 문서를 찾지 못했음을 API 계층에 알린다."""
    pass


class DocumentDeleteConflictError(Exception):
    """처리 중인 문서 삭제를 막기 위해 충돌 상태를 알린다."""
    pass


logger = logging.getLogger(__name__)
ACTIVE_DOCUMENT_STATUSES = {"uploaded", "processing"}


async def create_document_from_upload(db: Session, owner_id: int, file: UploadFile) -> Document:
    """업로드 행과 전용 파일을 저장하고 PDF 유효성을 확인한다."""
    title = Path((file.filename or "uploaded.pdf").replace("\\", "/")).name or "uploaded.pdf"
    # 문서 ID를 전용 저장 경로에 쓰기 위해 DB 행부터 생성한다.
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
        # 거부된 업로드는 DB 행과 불완전한 파일을 모두 정리한다.
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
    """소유권이 일치하는 문서를 조회하고 없으면 명시적으로 실패한다."""
    document = document_repository.get_document(db, document_id, owner_id, for_update=for_update)
    if document is None:
        raise DocumentNotFoundError
    return document


def list_documents(db: Session, owner_id: int) -> list[Document]:
    """현재 사용자가 소유한 문서를 생성 역순으로 조회한다."""
    return document_repository.list_documents(db, owner_id)


def delete_document(db: Session, document_id: int, owner_id: int) -> None:
    """삭제 가능 상태를 확인한 뒤 DB 행과 저장 파일을 정리한다."""
    document = get_document(db, document_id, owner_id, for_update=True)
    if document.status in ACTIVE_DOCUMENT_STATUSES:
        raise DocumentDeleteConflictError

    document_repository.delete_document(db, document)
    db.commit()

    try:
        LocalStorage().delete_document(document_id)
    except OSError:
        logger.exception("Failed to remove files for deleted document_id=%s", document_id)
