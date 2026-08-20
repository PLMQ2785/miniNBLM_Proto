import logging
import threading
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.retrieval_config import ReindexJob, RetrievalPresetRecord
from app.repositories import document_repository, retrieval_config_repository
from app.retrieval_presets import (
    RetrievalPreset,
    plan_preset_change,
)
from app.services.document_processor import process_document

logger = logging.getLogger(__name__)


class PresetNotFoundError(Exception):
    """요청한 검색 프리셋이 없음을 관리자 API에 알린다."""
    pass


class PresetChangeConflictError(Exception):
    """인덱싱 중인 문서나 유지보수 작업과의 충돌을 알린다."""
    pass


class PresetAlreadyActiveError(Exception):
    """이미 활성화된 프리셋으로의 중복 전환을 막는다."""
    pass


class ReindexJobNotFoundError(Exception):
    """재시도 대상으로 요청한 재인덱싱 작업이 없음을 알린다."""
    pass


class ReindexJobNotRetryableError(Exception):
    """완료되지 않았거나 실패하지 않은 작업의 재시도를 막는다."""
    pass


def start_reindex_worker(job_id: int) -> None:
    """런타임 복구가 재인덱싱 작업을 독립 백그라운드 스레드로 재개하게 한다."""
    worker = threading.Thread(
        target=run_reindex_job,
        args=(job_id,),
        name=f"reindex-job-{job_id}",
        daemon=True,
    )
    worker.start()


def recover_interrupted_reindex_jobs(db: Session) -> list[int]:
    """재시작 시 최신 미완료 작업만 유지보수 소유자로 복구한다."""
    configuration = retrieval_config_repository.get_configuration(db, for_update=True)
    unfinished_jobs = retrieval_config_repository.list_unfinished_reindex_jobs(db)
    now = datetime.now(UTC)

    if not unfinished_jobs:
        if configuration.maintenance_mode or configuration.pending_preset_key is not None:
            configuration.maintenance_mode = False
            configuration.pending_preset_key = None
            configuration.updated_at = now
            db.commit()
        return []

    # 재시작 뒤에는 가장 최근의 미완료 작업만 유지보수 모드를 소유한다.
    job = unfinished_jobs[-1]
    for superseded_job in unfinished_jobs[:-1]:
        superseded_job.status = "failed"
        superseded_job.error_message = "Superseded while recovering an interrupted reindex job"
        superseded_job.completed_at = now

    job.status = "pending"
    job.started_at = None
    job.completed_at = None
    job.total_documents = 0
    job.completed_documents = 0
    job.failed_documents = 0
    job.error_message = None
    configuration.pending_preset_key = job.target_preset_key
    configuration.maintenance_mode = True
    configuration.updated_at = now
    db.commit()
    return [job.id]


def _to_domain(record: RetrievalPresetRecord) -> RetrievalPreset:
    """DB 프리셋 레코드를 변경 계획 계산용 도메인 값으로 변환한다."""
    return RetrievalPreset(
        key=record.key,
        display_name=record.display_name,
        chunk_size_chars=record.chunk_size_chars,
        chunk_overlap_chars=record.chunk_overlap_chars,
        top_k=record.top_k,
    )


def start_preset_change(db: Session, requested_by: int, target_key: str) -> tuple[ReindexJob, bool]:
    """프리셋 차이를 계산해 즉시 전환하거나 재인덱싱 작업을 생성한다."""
    configuration = retrieval_config_repository.get_configuration(db, for_update=True)
    if configuration.maintenance_mode:
        raise PresetChangeConflictError("Another retrieval maintenance job is running")
    if document_repository.has_active_documents(db):
        raise PresetChangeConflictError("Wait for active document indexing to finish")

    source_record = retrieval_config_repository.get_preset(db, configuration.active_preset_key)
    target_record = retrieval_config_repository.get_preset(db, target_key)
    if target_record is None:
        raise PresetNotFoundError
    if source_record is None:
        raise RuntimeError("Active retrieval preset is missing")
    if source_record.key == target_record.key:
        raise PresetAlreadyActiveError

    change_plan = plan_preset_change(_to_domain(source_record), _to_domain(target_record))
    target_index_version = configuration.index_version + int(change_plan.reindex_documents)
    job = retrieval_config_repository.create_reindex_job(
        db,
        requested_by=requested_by,
        source_preset_key=source_record.key,
        target_preset_key=target_record.key,
        target_index_version=target_index_version,
        reindex_documents=change_plan.reindex_documents,
        rebuild_vector_index=False,
        runtime_settings_changed=change_plan.runtime_settings_changed,
    )

    # top-k만 바뀌면 즉시 반영하고 청크 구조가 바뀌면 전체를 다시 만든다.
    requires_background_work = change_plan.reindex_documents
    now = datetime.now(UTC)
    if requires_background_work:
        configuration.pending_preset_key = target_record.key
        configuration.maintenance_mode = True
    else:
        configuration.active_preset_key = target_record.key
        job.status = "completed"
        job.started_at = now
        job.completed_at = now
    configuration.updated_at = now
    db.commit()
    db.refresh(job)
    return job, requires_background_work


def retry_reindex_job(db: Session, requested_by: int, failed_job_id: int) -> ReindexJob:
    """실패한 작업의 목표 프리셋으로 새 전체 재인덱싱 작업을 만든다."""
    configuration = retrieval_config_repository.get_configuration(db, for_update=True)
    if configuration.maintenance_mode:
        raise PresetChangeConflictError("Another retrieval maintenance job is running")
    if document_repository.has_active_documents(db):
        raise PresetChangeConflictError("Wait for active document indexing to finish")

    failed_job = retrieval_config_repository.get_reindex_job(db, failed_job_id)
    if failed_job is None:
        raise ReindexJobNotFoundError
    if failed_job.status not in {"failed", "completed_with_errors"}:
        raise ReindexJobNotRetryableError
    if retrieval_config_repository.get_preset(db, failed_job.target_preset_key) is None:
        raise PresetNotFoundError

    target_index_version = configuration.index_version + 1
    retry_job = retrieval_config_repository.create_reindex_job(
        db,
        requested_by=requested_by,
        source_preset_key=configuration.active_preset_key,
        target_preset_key=failed_job.target_preset_key,
        target_index_version=target_index_version,
        reindex_documents=True,
        rebuild_vector_index=failed_job.rebuild_vector_index,
        runtime_settings_changed=failed_job.runtime_settings_changed,
    )
    configuration.pending_preset_key = failed_job.target_preset_key
    configuration.maintenance_mode = True
    configuration.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(retry_job)
    return retry_job


def run_reindex_job(job_id: int) -> None:
    """모든 문서를 목표 프리셋으로 재처리하고 유지보수 상태를 확정한다."""
    db = SessionLocal()
    try:
        job = retrieval_config_repository.get_reindex_job(db, job_id)
        if job is None or job.status != "pending":
            logger.warning("Reindex job %s is unavailable or not pending", job_id)
            return

        document_ids = (
            [document.id for document in document_repository.list_all_documents(db)]
            if job.reindex_documents
            else []
        )
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.total_documents = len(document_ids)
        db.commit()

        # 재시작 후에도 진행 기록이 남도록 문서마다 처리 결과를 확정한다.
        for document_id in document_ids:
            succeeded = process_document(
                document_id,
                preset_key=job.target_preset_key,
                index_version=job.target_index_version,
                reset_existing=job.reindex_documents,
            )
            db.refresh(job)
            if succeeded:
                job.completed_documents += 1
            else:
                job.failed_documents += 1
            db.commit()

        configuration = retrieval_config_repository.get_configuration(db, for_update=True)
        configuration.active_preset_key = job.target_preset_key
        configuration.pending_preset_key = None
        configuration.index_version = job.target_index_version
        configuration.maintenance_mode = False
        configuration.updated_at = datetime.now(UTC)

        job.status = "completed_with_errors" if job.failed_documents else "completed"
        job.completed_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        # 작업이 예기치 않게 끝나도 쓰기 차단 상태를 남기지 않는다.
        db.rollback()
        logger.exception("Reindex job failed: job_id=%s", job_id)
        job = retrieval_config_repository.get_reindex_job(db, job_id)
        configuration = retrieval_config_repository.get_configuration(db, for_update=True)
        if job is not None:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(UTC)
        configuration.pending_preset_key = None
        configuration.maintenance_mode = False
        configuration.updated_at = datetime.now(UTC)
        db.commit()
    finally:
        db.close()
