from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    session_id: int | None = Field(default=None, gt=0)


class SourceRef(BaseModel):
    document_id: int
    document_title: str
    page: int | None
    chunk_id: int
    available: bool = True


class ChatSessionSummary(BaseModel):
    session_id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ChatMessageResponse(BaseModel):
    message_id: int
    role: str
    content: str
    sources: list[SourceRef]
    created_at: datetime


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionSummary]


class ChatSessionDetail(ChatSessionSummary):
    messages: list[ChatMessageResponse]
    has_more: bool


class ChatResponse(BaseModel):
    session: ChatSessionSummary
    answer: str
    sources: list[SourceRef]
