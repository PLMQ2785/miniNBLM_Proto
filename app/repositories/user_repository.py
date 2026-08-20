from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatSession
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.page import DocumentPage
from app.models.user import AuthSession, User


def create_user(
    db: Session,
    username: str,
    password_hash: str,
    *,
    must_change_password: bool = False,
) -> User:
    user = User(
        username=username,
        password_hash=password_hash,
        role="user",
        must_change_password=must_change_password,
    )
    db.add(user)
    db.flush()
    return user

def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def delete_auth_sessions_for_user(db: Session, user_id: int) -> None:
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))


def set_user_role(db: Session, user: User, role: str) -> User:
    user.role = role
    db.flush()
    return user


def set_user_password_hash(db: Session, user: User, value: str) -> User:
    user.password_hash = value
    db.flush()
    return user


def set_password_change_required(db: Session, user: User, required: bool) -> User:
    user.must_change_password = required
    db.flush()
    return user


def create_auth_session(
    db: Session,
    user_id: int,
    token_hash: str,
    expires_at: datetime,
) -> AuthSession:
    auth_session = AuthSession(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    db.add(auth_session)
    db.flush()
    return auth_session


def get_user_by_session_token_hash(
    db: Session,
    token_hash: str,
    now: datetime,
) -> User | None:
    statement = (
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            AuthSession.token_hash == token_hash,
            AuthSession.expires_at > now,
            User.is_active.is_(True),
        )
    )
    return db.scalar(statement)


def delete_auth_session(db: Session, token_hash: str) -> None:
    db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash))


def delete_other_auth_sessions(db: Session, user_id: int, current_token_hash: str) -> None:
    db.execute(
        delete(AuthSession).where(
            AuthSession.user_id == user_id,
            AuthSession.token_hash != current_token_hash,
        )
    )


def list_owned_documents_for_update(db: Session, user_id: int) -> list[tuple[int, str]]:
    return list(
        db.execute(
            select(Document.id, Document.status)
            .where(Document.owner_id == user_id)
            .order_by(Document.id)
            .with_for_update()
        ).tuples()
    )


def delete_user_and_owned_data(db: Session, user: User, document_ids: list[int]) -> None:
    # Delete dependents explicitly; several relationships are intentionally workspace-wide.
    session_ids = list(
        db.scalars(select(ChatSession.id).where(ChatSession.owner_id == user.id))
    )
    if session_ids:
        db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(session_ids)))
        db.execute(delete(ChatSession).where(ChatSession.id.in_(session_ids)))

    if document_ids:
        db.execute(delete(Chunk).where(Chunk.document_id.in_(document_ids)))
        db.execute(delete(DocumentPage).where(DocumentPage.document_id.in_(document_ids)))
        db.execute(delete(Document).where(Document.id.in_(document_ids)))

    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.delete(user)
    db.flush()
