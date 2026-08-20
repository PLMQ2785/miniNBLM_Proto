import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.repositories import document_repository, retrieval_config_repository

logger = logging.getLogger(__name__)


def prepare_interrupted_documents(db: Session) -> list[int]:
    """재시작 시 중단 문서를 재처리 대상으로 되돌리고 원본 없는 문서는 실패 처리한다."""
    configuration = retrieval_config_repository.get_configuration(db)
    if configuration.maintenance_mode:
        logger.info("Document recovery is deferred to the active reindex job")
        return []

    recovered_document_ids: list[int] = []
    for document in document_repository.list_interrupted_documents(db):
        if not document.file_path or not Path(document.file_path).is_file():
            document_repository.update_status(
                db,
                document,
                "failed",
                "Original PDF is unavailable after an interrupted upload",
            )
            continue

        document_repository.update_status(db, document, "uploaded")
        recovered_document_ids.append(document.id)

    db.commit()
    return recovered_document_ids
