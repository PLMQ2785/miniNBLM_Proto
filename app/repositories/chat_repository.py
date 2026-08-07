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
    session = ChatSession(owner_id=owner_id, document_id=document_id, title=title)
    db.add(session)
    db.flush()
    return session


def get_session(db: Session, session_id: int, owner_id: int) -> ChatSession | None:
    return db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.owner_id == owner_id,
        )
    )


def list_sessions(db: Session, owner_id: int, *, limit: int, offset: int) -> list[ChatSession]:
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
    session.updated_at = datetime.now(timezone.utc)


def list_messages(
    db: Session,
    session_id: int,
    *,
    limit: int,
    before_id: int | None = None,
) -> tuple[list[ChatMessage], bool]:
    query = select(ChatMessage).where(ChatMessage.session_id == session_id)
    if before_id is not None:
        query = query.where(ChatMessage.id < before_id)
    rows = list(db.scalars(query.order_by(ChatMessage.id.desc()).limit(limit + 1)))
    has_more = len(rows) > limit
    return list(reversed(rows[:limit])), has_more


def list_recent_messages(db: Session, session_id: int, *, limit: int) -> list[ChatMessage]:
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
    db.delete(session)
    db.commit()


def delete_sessions_for_document(db: Session, document_id: int) -> None:
    sessions = list(db.scalars(select(ChatSession).where(ChatSession.document_id == document_id)))
    for chat_session in sessions:
        db.delete(chat_session)


def list_retrieval_traces(
    db: Session,
    *,
    limit: int,
    offset: int,
) -> list[tuple[ChatMessage, int, str]]:
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
