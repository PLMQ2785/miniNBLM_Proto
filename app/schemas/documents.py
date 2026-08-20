from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    """문서 API가 반환하는 문서 상태 경계다."""
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    title: str
    status: str
    created_at: datetime
    error_message: str | None = None


class DocumentUploadResponse(BaseModel):
    """업로드 API가 반환하는 접수 결과 경계다."""
    document_id: int
    status: str


class DocumentListResponse(BaseModel):
    """문서 목록 API의 최상위 응답 경계다."""
    documents: list[DocumentResponse]
