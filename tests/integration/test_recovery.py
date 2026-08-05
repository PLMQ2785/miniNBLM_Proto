from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.models.retrieval_config import ReindexJob
from app.repositories import retrieval_config_repository
from app.services.document_recovery_service import prepare_interrupted_documents
from app.services.reindex_service import recover_interrupted_reindex_jobs


pytestmark = pytest.mark.integration


def test_interrupted_documents_are_requeued_or_failed(
    db: Session,
    user_factory,
    document_factory,
) -> None:
    user = user_factory("recovery-user")
    recoverable = document_factory(user, title="recoverable.pdf", status="processing")
    missing = document_factory(
        user,
        title="missing.pdf",
        status="processing",
        file_exists=False,
    )

    recovered_ids = prepare_interrupted_documents(db)

    db.refresh(recoverable)
    db.refresh(missing)
    assert recovered_ids == [recoverable.id]
    assert recoverable.status == "uploaded"
    assert recoverable.error_message is None
    assert missing.status == "failed"
    assert "unavailable" in missing.error_message


def test_document_recovery_is_deferred_during_reindex(
    db: Session,
    user_factory,
    document_factory,
) -> None:
    user = user_factory("maintenance-user")
    document = document_factory(user, status="processing")
    configuration = retrieval_config_repository.get_configuration(db)
    configuration.maintenance_mode = True
    db.commit()

    assert prepare_interrupted_documents(db) == []

    db.refresh(document)
    assert document.status == "processing"


def test_running_reindex_job_is_reset_for_startup_retry(
    db: Session,
    user_factory,
) -> None:
    admin = user_factory("recovery-admin", role="admin")
    configuration = retrieval_config_repository.get_configuration(db)
    configuration.pending_preset_key = "standard"
    configuration.maintenance_mode = True
    job = ReindexJob(
        requested_by=admin.id,
        source_preset_key="balanced",
        target_preset_key="standard",
        target_index_version=2,
        status="running",
        reindex_documents=True,
        rebuild_vector_index=False,
        runtime_settings_changed=True,
        total_documents=7,
        completed_documents=3,
        failed_documents=1,
        error_message="interrupted",
        started_at=datetime.now(UTC),
    )
    db.add(job)
    db.commit()
    job_id = job.id

    recovered_ids = recover_interrupted_reindex_jobs(db)

    db.refresh(job)
    db.refresh(configuration)
    assert recovered_ids == [job_id]
    assert job.status == "pending"
    assert job.started_at is None
    assert job.completed_at is None
    assert job.total_documents == 0
    assert job.completed_documents == 0
    assert job.failed_documents == 0
    assert job.error_message is None
    assert configuration.pending_preset_key == "standard"
    assert configuration.maintenance_mode is True


def test_stale_maintenance_state_is_cleared_without_jobs(db: Session) -> None:
    configuration = retrieval_config_repository.get_configuration(db)
    configuration.pending_preset_key = "standard"
    configuration.maintenance_mode = True
    db.commit()

    assert recover_interrupted_reindex_jobs(db) == []

    db.refresh(configuration)
    assert configuration.pending_preset_key is None
    assert configuration.maintenance_mode is False
