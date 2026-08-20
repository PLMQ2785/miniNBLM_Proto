import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.dependencies import ensure_retrieval_writes_available, get_current_user, get_current_user_with_language_model, get_db
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from app.repositories import chat_repository, document_repository
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
from app.services import language_model_service

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


def _session_summary(session: ChatSession) -> ChatSessionSummary:
    """세션 목록과 완료 이벤트에 쓰는 공통 요약 응답을 만든다."""
    return ChatSessionSummary(
        session_id=session.id,
        document_id=session.document_id,
        title=session.title or "제목 없는 대화",
        created_at=session.created_at,
        updated_at=session.updated_at,
    )



def _require_indexed_document(
    db: Session,
    owner_id: int,
    document_id: int | None,
) -> None:
    """선택 문서가 있으면 소유권과 검색 가능 상태를 강제한다."""
    if document_id is None:
        return
    document = document_repository.get_document(db, document_id, owner_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if document.status != "indexed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document is not indexed",
        )


def _require_session_document(session: ChatSession, document_id: int | None) -> None:
    """대화 도중 전체·개별 문서 검색 범위가 바뀌는 것을 막는다."""
    if session.document_id != document_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chat session belongs to a different document scope",
        )


def _source_document_ids(messages: list[ChatMessage]) -> set[int]:
    """메시지 메타데이터에서 출처 문서 ID를 모아 제목 조회를 제한한다."""
    document_ids: set[int] = set()
    for message in messages:
        for source in (message.message_metadata or {}).get("sources", []):
            document_id = source.get("document_id") if isinstance(source, dict) else None
            if isinstance(document_id, int):
                document_ids.add(document_id)
    return document_ids


def _message_response(message: ChatMessage, document_titles: dict[int, str]) -> ChatMessageResponse:
    """저장 메시지를 현재 문서 가용성과 실제 인용 출처가 반영된 응답으로 바꾼다."""
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
    """최종 후처리 답변과 실제 인용 출처만 대화 기록에 함께 저장한다."""
    # 스트림 중간값이 아닌 최종 보정 답변과 실제 인용 출처만 저장한다.
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
    """이벤트와 JSON 데이터를 SSE 프레임 하나로 직렬화한다."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _cleanup_empty_session(session_id: int, owner_id: int) -> None:
    """새 스트림이 실패했을 때 메시지 없는 세션만 제거한다."""
    # 실패한 새 스트림이 빈 대화만 남기지 않게 한다.
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
    endpoint_key: str,
):
    """생성 델타·revision·출처·완료를 보내고 최종 교환을 별도 세션에 저장한다."""
    # 스트림은 요청 DB 세션보다 오래 살아 각 DB 단계가 자체 세션을 연다.
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
        stream_iterator = iter(streamed)
        while True:
            try:
                with language_model_service.use_endpoint(endpoint_key):
                    delta = next(stream_iterator)
            except StopIteration:
                break
            yield _sse("delta", {"text": delta})
        if streamed.generated is None:
            raise RuntimeError("Streaming answer completed without a final result")
        # 인용·리터럴 보정 뒤 revision은 이미 보낸 델타 전체를 교체한다.
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
    """현재 사용자의 대화 세션을 최신순 페이지로 반환한다."""
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
    """현재 사용자의 세션과 페이지 단위 메시지·출처 상태를 반환한다."""
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
    """현재 사용자 소유의 대화 세션을 삭제한다."""
    session = chat_repository.get_session(db, session_id, user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
    chat_repository.delete_session(db, session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_with_language_model),
    _: None = Depends(ensure_retrieval_writes_available),
) -> ChatResponse:
    """검색 계획부터 생성·인용 저장까지 동기 RAG 요청을 처리한다."""
    _require_indexed_document(db, user.id, request.document_id)
    if request.session_id is None:
        session = chat_repository.create_session(
            db,
            owner_id=user.id,
            document_id=request.document_id,
            title=request.question.strip()[:80] or "새 대화",
        )
        history: list[dict[str, str]] = []
    else:
        session = chat_repository.get_session(db, request.session_id, user.id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
        _require_session_document(session, request.document_id)
        recent_messages = chat_repository.list_recent_messages(
            db,
            session.id,
            limit=MAX_CONTEXT_MESSAGES,
        )
        history = build_conversation_context(recent_messages)

    # 동기와 SSE는 같은 검색 파이프라인을 쓰고 생성 전달 방식만 다르다.
    retrieval_plan = plan_retrieval_queries(request.question, history)
    trace = RetrievalTrace(request_id=request_id_context.get())
    goals = retrieval_plan.goals
    trace.set_query_plan(retrieval_plan.standalone_query, goals)
    chunks = retrieve_chunks(
        db=db,
        owner_id=user.id,
        document_id=request.document_id,
        question=retrieval_plan.standalone_query,
        goals=goals,
        trace=trace,
    )
    chunks = complete_evidence_coverage(
        db=db,
        owner_id=user.id,
        document_id=request.document_id,
        question=request.question,
        goals=goals,
        chunks=chunks,
        trace=trace,
    )
    evidence_matrix = build_evidence_matrix(goals, trace)
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
    user: User = Depends(get_current_user_with_language_model),
    _: None = Depends(ensure_retrieval_writes_available),
) -> StreamingResponse:
    """동기와 같은 검색을 마친 뒤 생성 결과를 SSE로 전달한다."""
    _require_indexed_document(db, user.id, request.document_id)
    owner_id = user.id
    session_created = request.session_id is None
    if session_created:
        history: list[dict[str, str]] = []
        session = None
    else:
        session = chat_repository.get_session(db, request.session_id, owner_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
        _require_session_document(session, request.document_id)
        recent_messages = chat_repository.list_recent_messages(
            db,
            session.id,
            limit=MAX_CONTEXT_MESSAGES,
        )
        history = build_conversation_context(recent_messages)

    retrieval_plan = plan_retrieval_queries(request.question, history)
    trace = RetrievalTrace(request_id=request_id_context.get())
    goals = retrieval_plan.goals
    trace.set_query_plan(retrieval_plan.standalone_query, goals)
    chunks = retrieve_chunks(
        db=db,
        owner_id=owner_id,
        document_id=request.document_id,
        question=retrieval_plan.standalone_query,
        goals=goals,
        trace=trace,
    )
    chunks = complete_evidence_coverage(
        db=db,
        owner_id=owner_id,
        document_id=request.document_id,
        question=request.question,
        goals=goals,
        chunks=chunks,
        trace=trace,
    )
    evidence_matrix = build_evidence_matrix(goals, trace)
    # 검색 성공 뒤에만 새 세션을 만들어 실패한 빈 대화를 피한다.
    if session is None:
        session = chat_repository.create_session(
            db,
            owner_id=owner_id,
            document_id=request.document_id,
            title=request.question.strip()[:80] or "새 대화",
        )
        db.commit()
        db.refresh(session)

    stream_session_id = session.id
    endpoint_key = language_model_service.get_user_endpoint_key(user)
    # 생성기는 요청 범위 DB 세션을 닫은 뒤 실행된다.
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
            endpoint_key=endpoint_key,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
