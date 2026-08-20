from datetime import datetime
from typing import Any

from pydantic import BaseModel


class RetrievalPresetResponse(BaseModel):
    """관리 API가 반환하는 검색 프리셋 경계다."""
    key: str
    display_name: str
    chunk_size_chars: int
    chunk_overlap_chars: int
    top_k: int


class SearchAlgorithmResponse(BaseModel):
    """관리 API가 반환하는 검색 알고리즘 경계다."""
    key: str
    display_name: str
    description: str


class ReindexJobResponse(BaseModel):
    """관리 API가 반환하는 재색인 작업 상태 경계다."""
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
    """관리 API가 반환하는 검색 설정 전체 상태 경계다."""
    presets: list[RetrievalPresetResponse]
    search_algorithms: list[SearchAlgorithmResponse]
    active_preset_key: str
    active_search_algorithm_key: str
    pending_preset_key: str | None
    index_version: int
    maintenance_mode: bool
    latest_job: ReindexJobResponse | None


class RetrievalTraceResponse(BaseModel):
    """관리 API가 노출하는 메시지별 검색 추적 경계다."""
    message_id: int
    session_id: int
    owner_id: int
    username: str
    created_at: datetime
    trace: dict[str, Any]


class RetrievalTraceListResponse(BaseModel):
    """관리 API가 반환하는 검색 추적 목록 경계다."""
    traces: list[RetrievalTraceResponse]
