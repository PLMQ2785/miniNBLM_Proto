from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatSession
from app.models.document import Document
from app.models.user import User


def create_session(
    db: Session,
    owner_id: int,
    document_id: int | None = None,
    title: str | None = None,
) -> ChatSession:
    """사용자 소유 대화 세션을 추가하고 호출자 트랜잭션에서 확정한다."""
    session = ChatSession(owner_id=owner_id, document_id=document_id, title=title)
    db.add(session)
    db.flush()
    return session


def get_session(db: Session, session_id: int, owner_id: int) -> ChatSession | None:
    """세션 식별자와 소유자를 함께 제한해 대화를 조회한다."""
    return db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.owner_id == owner_id,
        )
    )


def list_sessions(db: Session, owner_id: int, *, limit: int, offset: int) -> list[ChatSession]:
    """사용자 소유 대화 세션을 최근 활동순으로 나눠 조회한다."""
    return list(
        db.scalars(
            select(ChatSession)
            .where(ChatSession.owner_id == owner_id)
            .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def create_message(
    db: Session,
    session_id: int,
    role: str,
    content: str,
    retrieved_chunk_ids: list[int] | None = None,
    metadata: dict | None = None,
) -> ChatMessage:
    """세션 소유 메시지를 추가하고 호출자 트랜잭션에서 확정한다."""
    message = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        retrieved_chunk_ids=retrieved_chunk_ids,
        message_metadata=metadata,
    )
    db.add(message)
    db.flush()
    return message


def touch_session(session: ChatSession) -> None:
    """새 메시지 뒤 정렬 기준이 되도록 세션 활동 시각을 갱신한다."""
    session.updated_at = datetime.now(timezone.utc)


def list_messages(
    db: Session,
    session_id: int,
    *,
    limit: int,
    before_id: int | None = None,
) -> tuple[list[ChatMessage], bool]:
    """세션 메시지를 커서 방식으로 조회하고 다음 페이지 여부를 돌려준다."""
    query = select(ChatMessage).where(ChatMessage.session_id == session_id)
    if before_id is not None:
        query = query.where(ChatMessage.id < before_id)
    rows = list(db.scalars(query.order_by(ChatMessage.id.desc()).limit(limit + 1)))
    has_more = len(rows) > limit
    return list(reversed(rows[:limit])), has_more


def list_recent_messages(db: Session, session_id: int, *, limit: int) -> list[ChatMessage]:
    """모델 문맥에 쓸 최근 세션 메시지를 시간순으로 조회한다."""
    rows = list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )
    )
    return list(reversed(rows))


def get_source_document_titles(
    db: Session,
    owner_id: int,
    document_ids: set[int],
) -> dict[int, str]:
    """사용자 소유 문서만 허용해 출처 제목을 조회한다."""
    if not document_ids:
        return {}
    rows = db.execute(
        select(Document.id, Document.title).where(
            Document.owner_id == owner_id,
            Document.id.in_(document_ids),
        )
    )
    return {document_id: title for document_id, title in rows}


def delete_session(db: Session, session: ChatSession) -> None:
    """대화 세션을 삭제하고 이 저장소 경계에서 즉시 커밋한다."""
    db.delete(session)
    db.commit()


def delete_sessions_for_document(db: Session, document_id: int) -> None:
    """문서에 종속된 대화 세션을 삭제하고 커밋은 호출자에게 맡긴다."""
    sessions = list(db.scalars(select(ChatSession).where(ChatSession.document_id == document_id)))
    for chat_session in sessions:
        db.delete(chat_session)


def list_retrieval_traces(
    db: Session,
    *,
    limit: int,
    offset: int,
) -> list[tuple[ChatMessage, int, str]]:
    """관리 화면용 검색 추적을 사용자 정보와 함께 조회한다."""
    return list(
        db.execute(
            select(ChatMessage, ChatSession.owner_id, User.username)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .join(User, User.id == ChatSession.owner_id)
            .where(
                ChatMessage.role == "assistant",
                ChatMessage.message_metadata.is_not(None),
                ChatMessage.message_metadata.has_key("retrieval_trace"),  # type: ignore[attr-defined]
            )
            .order_by(ChatMessage.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
