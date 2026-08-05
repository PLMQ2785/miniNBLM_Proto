from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    title: str
    status: str
    created_at: datetime
    error_message: str | None = None


class DocumentUploadResponse(BaseModel):
    document_id: int
    status: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
