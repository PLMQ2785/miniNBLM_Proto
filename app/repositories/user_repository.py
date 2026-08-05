from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

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


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


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
