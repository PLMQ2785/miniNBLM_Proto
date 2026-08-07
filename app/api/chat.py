import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import SessionLocal
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
from app.observability import CHAT_STREAMS, request_id_context
from app.services.generator import StreamingAnswer, cited_source_indexes, generate_answer
from app.services.evidence_coverage import build_evidence_matrix, complete_evidence_coverage
from app.services.query_rewriter import plan_retrieval_queries
from app.services.retriever import retrieve_chunks
from app.services.retrieval_trace import RetrievalTrace

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


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
    metadata = message.message_metadata or {}
    raw_sources = metadata.get("sources", [])
    if not isinstance(raw_sources, list):
        raw_sources = []
    if message.role == "assistant" and metadata.get("source_selection") != "cited":
        raw_sources = [
            raw_sources[index]
            for index in cited_source_indexes(message.content, len(raw_sources))
        ]
    sources: list[SourceRef] = []
    for raw_source in raw_sources:
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


def _persist_exchange(
    db: Session,
    session: ChatSession,
    question: str,
    answer: str,
    chunks,
    sources: list[SourceRef],
    trace: RetrievalTrace | None = None,
) -> None:
    trace_metadata = (
        trace.complete(answer=answer, chunks=chunks, sources=sources)
        if trace is not None
        else None
    )
    chat_repository.create_message(db, session.id, "user", question)
    chat_repository.create_message(
        db,
        session.id,
        "assistant",
        answer,
        retrieved_chunk_ids=[chunk.chunk_id for chunk in chunks],
        metadata={
            "sources": [source.model_dump() for source in sources],
            "source_selection": "cited",
            **({"retrieval_trace": trace_metadata} if trace_metadata is not None else {}),
        },
    )
    chat_repository.touch_session(session)
    if trace_metadata is not None:
        logger.info("Retrieval trace completed", extra={"retrieval_trace": trace_metadata})


def _sse(event: str, payload: dict | list) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _cleanup_empty_session(session_id: int, owner_id: int) -> None:
    with SessionLocal() as db:
        session = chat_repository.get_session(db, session_id, owner_id)
        if session is not None and not session.messages:
            chat_repository.delete_session(db, session)


def _chat_event_stream(
    *,
    session_id: int,
    owner_id: int,
    session_created: bool,
    question: str,
    chunks,
    history: list[dict[str, str]],
    trace: RetrievalTrace,
    evidence_matrix,
):
    try:
        with SessionLocal() as db:
            session = chat_repository.get_session(db, session_id, owner_id)
            if session is None:
                raise RuntimeError("Chat session disappeared before streaming started")
            yield _sse("session", _session_summary(session).model_dump(mode="json"))

        streamed = StreamingAnswer(
            question=question,
            chunks=chunks,
            history=history,
            evidence_matrix=evidence_matrix,
        )
        for delta in streamed:
            yield _sse("delta", {"text": delta})
        if streamed.generated is None:
            raise RuntimeError("Streaming answer completed without a final result")
        if streamed.revision is not None:
            yield _sse("revision", {"text": streamed.revision})

        with SessionLocal() as db:
            session = chat_repository.get_session(db, session_id, owner_id)
            if session is None:
                raise RuntimeError("Chat session disappeared before persistence")
            _persist_exchange(
                db,
                session,
                question,
                streamed.generated.answer,
                chunks,
                streamed.generated.sources,
                trace,
            )
            db.commit()
            db.refresh(session)
            final_session = _session_summary(session).model_dump(mode="json")

        yield _sse(
            "sources",
            [source.model_dump(mode="json") for source in streamed.generated.sources],
        )
        yield _sse("done", {"session": final_session})
        CHAT_STREAMS.labels(status="success").inc()
    except GeneratorExit:
        CHAT_STREAMS.labels(status="cancelled").inc()
        if session_created:
            _cleanup_empty_session(session_id, owner_id)
        raise
    except Exception:
        CHAT_STREAMS.labels(status="error").inc()
        logger.exception("Chat stream failed")
        if session_created:
            _cleanup_empty_session(session_id, owner_id)
        yield _sse(
            "error",
            {
                "detail": "답변 스트리밍 중 오류가 발생했습니다.",
                "request_id": request_id_context.get(),
            },
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

    retrieval_plan = plan_retrieval_queries(request.question, history)
    trace = RetrievalTrace(request_id=request_id_context.get())
    evidence_goals = retrieval_plan.evidence_goals or retrieval_plan.queries
    trace.set_query_plan(
        retrieval_plan.standalone_query,
        retrieval_plan.queries,
        evidence_goals,
    )
    chunks = retrieve_chunks(
        db=db,
        owner_id=user.id,
        question=retrieval_plan.standalone_query,
        queries=retrieval_plan.queries,
        trace=trace,
    )
    chunks = complete_evidence_coverage(
        db=db,
        owner_id=user.id,
        question=request.question,
        queries=evidence_goals,
        chunks=chunks,
        trace=trace,
    )
    evidence_matrix = build_evidence_matrix(evidence_goals, trace)
    generated = generate_answer(
        question=request.question,
        chunks=chunks,
        history=history,
        evidence_matrix=evidence_matrix,
    )

    _persist_exchange(
        db,
        session,
        request.question,
        generated.answer,
        chunks,
        generated.sources,
        trace,
    )
    db.commit()
    db.refresh(session)

    return ChatResponse(
        session=_session_summary(session),
        answer=generated.answer,
        sources=generated.sources,
    )


@router.post("/stream", response_class=StreamingResponse)
def chat_stream(
    request: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(ensure_retrieval_writes_available),
) -> StreamingResponse:
    owner_id = user.id
    session_created = request.session_id is None
    if session_created:
        history: list[dict[str, str]] = []
        session = None
    else:
        session = chat_repository.get_session(db, request.session_id, owner_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
        recent_messages = chat_repository.list_recent_messages(
            db,
            session.id,
            limit=MAX_CONTEXT_MESSAGES,
        )
        history = build_conversation_context(recent_messages)

    retrieval_plan = plan_retrieval_queries(request.question, history)
    trace = RetrievalTrace(request_id=request_id_context.get())
    evidence_goals = retrieval_plan.evidence_goals or retrieval_plan.queries
    trace.set_query_plan(
        retrieval_plan.standalone_query,
        retrieval_plan.queries,
        evidence_goals,
    )
    chunks = retrieve_chunks(
        db=db,
        owner_id=owner_id,
        question=retrieval_plan.standalone_query,
        queries=retrieval_plan.queries,
        trace=trace,
    )
    chunks = complete_evidence_coverage(
        db=db,
        owner_id=owner_id,
        question=request.question,
        queries=evidence_goals,
        chunks=chunks,
        trace=trace,
    )
    evidence_matrix = build_evidence_matrix(evidence_goals, trace)

    if session is None:
        session = chat_repository.create_session(
            db,
            owner_id=owner_id,
            title=request.question.strip()[:80] or "새 대화",
        )
        db.commit()
        db.refresh(session)

    stream_session_id = session.id
    db.close()
    return StreamingResponse(
        _chat_event_stream(
            session_id=stream_session_id,
            owner_id=owner_id,
            session_created=session_created,
            question=request.question,
            chunks=chunks,
            history=history,
            trace=trace,
            evidence_matrix=evidence_matrix,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
