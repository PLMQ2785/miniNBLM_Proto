from datetime import datetime
from typing import Any

from pydantic import BaseModel


class RetrievalPresetResponse(BaseModel):
    key: str
    display_name: str
    chunk_size_chars: int
    chunk_overlap_chars: int
    top_k: int


class SearchAlgorithmResponse(BaseModel):
    key: str
    display_name: str
    description: str


class ReindexJobResponse(BaseModel):
    job_id: int
    source_preset_key: str
    target_preset_key: str
    target_index_version: int
    status: str
    reindex_documents: bool
    rebuild_vector_index: bool
    runtime_settings_changed: bool
    total_documents: int
    completed_documents: int
    failed_documents: int
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class RetrievalAdminStateResponse(BaseModel):
    presets: list[RetrievalPresetResponse]
    search_algorithms: list[SearchAlgorithmResponse]
    active_preset_key: str
    active_search_algorithm_key: str
    pending_preset_key: str | None
    index_version: int
    maintenance_mode: bool
    latest_job: ReindexJobResponse | None


class RetrievalTraceResponse(BaseModel):
    message_id: int
    session_id: int
    owner_id: int
    username: str
    created_at: datetime
    trace: dict[str, Any]


class RetrievalTraceListResponse(BaseModel):
    traces: list[RetrievalTraceResponse]
