import logging

from app.database import SessionLocal
from app.services import (
    auth_service,
    document_processor,
    document_recovery_service,
    reindex_service,
)

logger = logging.getLogger(__name__)


def initialize_runtime() -> None:
    """부팅 관리자를 보장하고 중단된 재인덱싱·문서 처리를 안전하게 재개한다."""
    db = SessionLocal()
    try:
        admin = auth_service.ensure_bootstrap_admin(db)
        admin_username = admin.username if admin is not None else None
        recovered_job_ids = reindex_service.recover_interrupted_reindex_jobs(db)
        recovered_document_ids = document_recovery_service.prepare_interrupted_documents(db)
    except Exception:
        db.rollback()
        logger.exception("Runtime initialization failed")
        raise
    finally:
        db.close()

    if admin_username is not None:
        logger.info("Bootstrap administrator is ready: username=%s", admin_username)
    for job_id in recovered_job_ids:
        logger.warning("Resuming interrupted reindex job: job_id=%s", job_id)
        reindex_service.start_reindex_worker(job_id)
    for document_id in recovered_document_ids:
        logger.warning("Resuming interrupted document indexing: document_id=%s", document_id)
        document_processor.start_document_worker(document_id, reset_existing=True)
