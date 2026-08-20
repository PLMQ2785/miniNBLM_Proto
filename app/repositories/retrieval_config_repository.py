from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.retrieval_config import (
    ReindexJob,
    RetrievalConfiguration,
    RetrievalPresetRecord,
    SearchAlgorithmRecord,
)


def list_presets(db: Session) -> list[RetrievalPresetRecord]:
    """관리 API용 검색 프리셋을 청크 크기순으로 조회한다."""
    return list(db.scalars(select(RetrievalPresetRecord).order_by(RetrievalPresetRecord.chunk_size_chars)))


def get_preset(db: Session, key: str) -> RetrievalPresetRecord | None:
    """키로 검색 프리셋을 조회하며 트랜잭션은 호출자가 관리한다."""
    return db.get(RetrievalPresetRecord, key)


def list_search_algorithms(db: Session) -> list[SearchAlgorithmRecord]:
    """관리 API용 검색 알고리즘을 등록순으로 조회한다."""
    return list(db.scalars(select(SearchAlgorithmRecord).order_by(SearchAlgorithmRecord.created_at)))


def get_search_algorithm(db: Session, key: str) -> SearchAlgorithmRecord | None:
    """키로 검색 알고리즘을 조회하며 트랜잭션은 호출자가 관리한다."""
    return db.get(SearchAlgorithmRecord, key)


def get_configuration(db: Session, *, for_update: bool = False) -> RetrievalConfiguration:
    """단일 검색 설정을 조회하고 변경 경계에서는 행을 잠근다."""
    statement = select(RetrievalConfiguration).where(RetrievalConfiguration.id == 1)
    if for_update:
        statement = statement.with_for_update()
    configuration = db.scalar(statement)
    if configuration is None:
        raise RuntimeError("Retrieval configuration is not initialized")
    return configuration


def create_reindex_job(
    db: Session,
    *,
    requested_by: int,
    source_preset_key: str,
    target_preset_key: str,
    target_index_version: int,
    reindex_documents: bool,
    rebuild_vector_index: bool,
    runtime_settings_changed: bool,
) -> ReindexJob:
    """재색인 작업을 추가하고 호출자 트랜잭션에서 식별자를 확정한다."""
    job = ReindexJob(
        requested_by=requested_by,
        source_preset_key=source_preset_key,
        target_preset_key=target_preset_key,
        target_index_version=target_index_version,
        reindex_documents=reindex_documents,
        rebuild_vector_index=rebuild_vector_index,
        runtime_settings_changed=runtime_settings_changed,
    )
    db.add(job)
    db.flush()
    return job


def get_reindex_job(db: Session, job_id: int) -> ReindexJob | None:
    """식별자로 재색인 작업을 조회한다."""
    return db.get(ReindexJob, job_id)


def get_latest_reindex_job(db: Session) -> ReindexJob | None:
    """관리 상태에 표시할 가장 최근 재색인 작업을 조회한다."""
    return db.scalar(select(ReindexJob).order_by(ReindexJob.created_at.desc()).limit(1))


def list_unfinished_reindex_jobs(db: Session) -> list[ReindexJob]:
    """복구 작업이 이어갈 미완료 재색인 행을 잠가 조회한다."""
    statement = (
        select(ReindexJob)
        .where(ReindexJob.status.in_(("pending", "running")))
        .order_by(ReindexJob.created_at, ReindexJob.id)
        .with_for_update()
    )
    return list(db.scalars(statement))
