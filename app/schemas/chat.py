from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """대화 API가 받는 질문과 세션 선택 경계다."""
    question: str = Field(min_length=1)
    session_id: int | None = Field(default=None, gt=0)


class SourceRef(BaseModel):
    """대화 응답에서 출처 문서와 청크를 식별하는 경계다."""
    document_id: int
    document_title: str
    page: int | None
    chunk_id: int
    available: bool = True


class ChatSessionSummary(BaseModel):
    """대화 목록 API가 반환하는 세션 요약 경계다."""
    session_id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ChatMessageResponse(BaseModel):
    """대화 상세 API가 반환하는 개별 메시지 경계다."""
    message_id: int
    role: str
    content: str
    sources: list[SourceRef]
    created_at: datetime


class ChatSessionListResponse(BaseModel):
    """대화 목록 API의 최상위 응답 경계다."""
    sessions: list[ChatSessionSummary]


class ChatSessionDetail(ChatSessionSummary):
    """대화 상세 API가 반환하는 메시지와 페이지 상태 경계다."""
    messages: list[ChatMessageResponse]
    has_more: bool


class ChatResponse(BaseModel):
    """질문 API가 반환하는 답변·출처·세션 경계다."""
    session: ChatSessionSummary
    answer: str
    sources: list[SourceRef]
