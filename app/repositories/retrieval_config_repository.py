from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.retrieval_config import (
    ReindexJob,
    RetrievalConfiguration,
    RetrievalPresetRecord,
    SearchAlgorithmRecord,
)


def list_presets(db: Session) -> list[RetrievalPresetRecord]:
    return list(db.scalars(select(RetrievalPresetRecord).order_by(RetrievalPresetRecord.chunk_size_chars)))


def get_preset(db: Session, key: str) -> RetrievalPresetRecord | None:
    return db.get(RetrievalPresetRecord, key)


def list_search_algorithms(db: Session) -> list[SearchAlgorithmRecord]:
    return list(db.scalars(select(SearchAlgorithmRecord).order_by(SearchAlgorithmRecord.created_at)))


def get_search_algorithm(db: Session, key: str) -> SearchAlgorithmRecord | None:
    return db.get(SearchAlgorithmRecord, key)


def get_configuration(db: Session, *, for_update: bool = False) -> RetrievalConfiguration:
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
    return db.get(ReindexJob, job_id)


def get_latest_reindex_job(db: Session) -> ReindexJob | None:
    return db.scalar(select(ReindexJob).order_by(ReindexJob.created_at.desc()).limit(1))


def list_unfinished_reindex_jobs(db: Session) -> list[ReindexJob]:
    statement = (
        select(ReindexJob)
        .where(ReindexJob.status.in_(("pending", "running")))
        .order_by(ReindexJob.created_at, ReindexJob.id)
        .with_for_update()
    )
    return list(db.scalars(statement))
