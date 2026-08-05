from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_admin, get_db
from app.models.retrieval_config import ReindexJob, RetrievalPresetRecord, SearchAlgorithmRecord
from app.models.user import User
from app.repositories import retrieval_config_repository
from app.schemas.admin_retrieval import (
    ReindexJobResponse,
    RetrievalAdminStateResponse,
    RetrievalPresetResponse,
    SearchAlgorithmResponse,
)
from app.services import reindex_service, search_algorithm_service
from app.services.reindex_service import (
    PresetAlreadyActiveError,
    PresetChangeConflictError,
    PresetNotFoundError,
    ReindexJobNotFoundError,
    ReindexJobNotRetryableError,
)
from app.services.search_algorithm_service import (
    SearchAlgorithmChangeConflictError,
    SearchAlgorithmNotFoundError,
)

router = APIRouter(prefix="/admin/retrieval", tags=["admin-retrieval"])


def _preset_response(preset: RetrievalPresetRecord) -> RetrievalPresetResponse:
    return RetrievalPresetResponse(
        key=preset.key,
        display_name=preset.display_name,
        chunk_size_chars=preset.chunk_size_chars,
        chunk_overlap_chars=preset.chunk_overlap_chars,
        top_k=preset.top_k,
    )


def _search_algorithm_response(algorithm: SearchAlgorithmRecord) -> SearchAlgorithmResponse:
    return SearchAlgorithmResponse(
        key=algorithm.key,
        display_name=algorithm.display_name,
        description=algorithm.description,
    )


def _job_response(job: ReindexJob) -> ReindexJobResponse:
    return ReindexJobResponse(
        job_id=job.id,
        source_preset_key=job.source_preset_key,
        target_preset_key=job.target_preset_key,
        target_index_version=job.target_index_version,
        status=job.status,
        reindex_documents=job.reindex_documents,
        rebuild_vector_index=job.rebuild_vector_index,
        runtime_settings_changed=job.runtime_settings_changed,
        total_documents=job.total_documents,
        completed_documents=job.completed_documents,
        failed_documents=job.failed_documents,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.get("", response_model=RetrievalAdminStateResponse)
def get_retrieval_state(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> RetrievalAdminStateResponse:
    configuration = retrieval_config_repository.get_configuration(db)
    latest_job = retrieval_config_repository.get_latest_reindex_job(db)
    return RetrievalAdminStateResponse(
        presets=[_preset_response(preset) for preset in retrieval_config_repository.list_presets(db)],
        search_algorithms=[
            _search_algorithm_response(algorithm)
            for algorithm in retrieval_config_repository.list_search_algorithms(db)
        ],
        active_preset_key=configuration.active_preset_key,
        active_search_algorithm_key=configuration.active_search_algorithm_key,
        pending_preset_key=configuration.pending_preset_key,
        index_version=configuration.index_version,
        maintenance_mode=configuration.maintenance_mode,
        latest_job=_job_response(latest_job) if latest_job else None,
    )


@router.post(
    "/algorithms/{algorithm_key}/activate",
    response_model=SearchAlgorithmResponse,
)
def activate_search_algorithm(
    algorithm_key: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> SearchAlgorithmResponse:
    try:
        algorithm = search_algorithm_service.activate_search_algorithm(db, algorithm_key)
    except SearchAlgorithmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search algorithm not found") from exc
    except SearchAlgorithmChangeConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _search_algorithm_response(algorithm)


@router.post(
    "/presets/{preset_key}/activate",
    response_model=ReindexJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def activate_preset(
    preset_key: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> ReindexJobResponse:
    try:
        job, requires_background_work = reindex_service.start_preset_change(db, admin.id, preset_key)
    except PresetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Retrieval preset not found") from exc
    except PresetAlreadyActiveError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Retrieval preset is already active") from exc
    except PresetChangeConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if requires_background_work:
        background_tasks.add_task(reindex_service.run_reindex_job, job.id)
    return _job_response(job)


@router.get("/jobs/{job_id}", response_model=ReindexJobResponse)
def get_reindex_job(
    job_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> ReindexJobResponse:
    job = retrieval_config_repository.get_reindex_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reindex job not found")
    return _job_response(job)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=ReindexJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_reindex_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> ReindexJobResponse:
    try:
        retry_job = reindex_service.retry_reindex_job(db, admin.id, job_id)
    except ReindexJobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reindex job not found") from exc
    except ReindexJobNotRetryableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Reindex job is not retryable") from exc
    except PresetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Retrieval preset not found") from exc
    except PresetChangeConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    background_tasks.add_task(reindex_service.run_reindex_job, retry_job.id)
    return _job_response(retry_job)
