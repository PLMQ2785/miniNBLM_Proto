from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatSession


def create_session(db: Session, owner_id: int, document_id: int, title: str | None = None) -> ChatSession:
    session = ChatSession(owner_id=owner_id, document_id=document_id, title=title)
    db.add(session)
    db.flush()
    return session


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


def delete_sessions_for_document(db: Session, document_id: int) -> None:
    sessions = list(db.scalars(select(ChatSession).where(ChatSession.document_id == document_id)))
    for chat_session in sessions:
        db.delete(chat_session)
