from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.dependencies import ensure_retrieval_writes_available, get_current_user, get_db
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from app.repositories import chat_repository
from app.schemas.chat import (
    ChatMessageResponse,
    ChatRequest,
    ChatResponse,
    ChatSessionDetail,
    ChatSessionListResponse,
    ChatSessionSummary,
    SourceRef,
)
from app.services.conversation_service import MAX_CONTEXT_MESSAGES, build_conversation_context
from app.services.generator import generate_answer
from app.services.retriever import retrieve_chunks

router = APIRouter(prefix="/chat", tags=["chat"])


def _session_summary(session: ChatSession) -> ChatSessionSummary:
    return ChatSessionSummary(
        session_id=session.id,
        title=session.title or "제목 없는 대화",
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _source_document_ids(messages: list[ChatMessage]) -> set[int]:
    document_ids: set[int] = set()
    for message in messages:
        for source in (message.message_metadata or {}).get("sources", []):
            document_id = source.get("document_id") if isinstance(source, dict) else None
            if isinstance(document_id, int):
                document_ids.add(document_id)
    return document_ids


def _message_response(message: ChatMessage, document_titles: dict[int, str]) -> ChatMessageResponse:
    sources: list[SourceRef] = []
    for raw_source in (message.message_metadata or {}).get("sources", []):
        if not isinstance(raw_source, dict) or not isinstance(raw_source.get("document_id"), int):
            continue
        document_id = raw_source["document_id"]
        try:
            sources.append(
                SourceRef.model_validate(
                    {
                        **raw_source,
                        "document_title": raw_source.get("document_title")
                        or document_titles.get(document_id)
                        or "문서",
                        "available": document_id in document_titles,
                    }
                )
            )
        except ValueError:
            continue
    return ChatMessageResponse(
        message_id=message.id,
        role=message.role,
        content=message.content,
        sources=sources,
        created_at=message.created_at,
    )


@router.get("/sessions", response_model=ChatSessionListResponse)
def list_chat_sessions(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatSessionListResponse:
    sessions = chat_repository.list_sessions(db, user.id, limit=limit, offset=offset)
    return ChatSessionListResponse(sessions=[_session_summary(session) for session in sessions])


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
def get_chat_session(
    session_id: int,
    limit: int = Query(default=100, ge=1, le=100),
    before_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatSessionDetail:
    session = chat_repository.get_session(db, session_id, user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    messages, has_more = chat_repository.list_messages(
        db,
        session.id,
        limit=limit,
        before_id=before_id,
    )
    document_titles = chat_repository.get_source_document_titles(
        db,
        user.id,
        _source_document_ids(messages),
    )
    summary = _session_summary(session)
    return ChatSessionDetail(
        **summary.model_dump(),
        messages=[_message_response(message, document_titles) for message in messages],
        has_more=has_more,
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    session = chat_repository.get_session(db, session_id, user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
    chat_repository.delete_session(db, session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(ensure_retrieval_writes_available),
) -> ChatResponse:
    if request.session_id is None:
        session = chat_repository.create_session(
            db,
            owner_id=user.id,
            title=request.question.strip()[:80] or "새 대화",
        )
        history: list[dict[str, str]] = []
    else:
        session = chat_repository.get_session(db, request.session_id, user.id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
        recent_messages = chat_repository.list_recent_messages(
            db,
            session.id,
            limit=MAX_CONTEXT_MESSAGES,
        )
        history = build_conversation_context(recent_messages)

    chunks = retrieve_chunks(db=db, owner_id=user.id, question=request.question)
    generated = generate_answer(question=request.question, chunks=chunks, history=history)

    chat_repository.create_message(db, session.id, "user", request.question)
    chat_repository.create_message(
        db,
        session.id,
        "assistant",
        generated.answer,
        retrieved_chunk_ids=[chunk.chunk_id for chunk in chunks],
        metadata={"sources": [source.model_dump() for source in generated.sources]},
    )
    chat_repository.touch_session(session)
    db.commit()
    db.refresh(session)

    return ChatResponse(
        session=_session_summary(session),
        answer=generated.answer,
        sources=generated.sources,
    )
