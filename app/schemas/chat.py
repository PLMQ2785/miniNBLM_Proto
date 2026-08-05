from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    document_id: int
    question: str = Field(min_length=1)


class SourceRef(BaseModel):
    document_id: int
    page: int | None
    chunk_id: int


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceRef]
