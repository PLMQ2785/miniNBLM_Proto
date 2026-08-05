import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User
from app.repositories import user_repository


class UsernameAlreadyExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


@dataclass(frozen=True)
class AuthenticatedSession:
    user: User
    token: str


password_hash = PasswordHash.recommended()
dummy_password_hash = password_hash.hash("not-a-real-user-password")


def _hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=settings.auth_session_ttl_hours)
    user_repository.create_auth_session(db, user.id, _hash_session_token(token), expires_at)
    return token


def register(db: Session, username: str, password: str) -> AuthenticatedSession:
    try:
        user = user_repository.create_user(db, username, password_hash.hash(password))
    except IntegrityError as exc:
        db.rollback()
        raise UsernameAlreadyExistsError from exc

    token = _create_session(db, user)
    db.commit()
    db.refresh(user)
    return AuthenticatedSession(user=user, token=token)


def login(db: Session, username: str, password: str) -> AuthenticatedSession:
    user = user_repository.get_user_by_username(db, username)
    candidate_hash = user.password_hash if user is not None and user.is_active else dummy_password_hash
    try:
        password_valid = password_hash.verify(password, candidate_hash)
    except Exception:
        password_valid = False
    if user is None or not user.is_active or not password_valid:
        raise InvalidCredentialsError

    token = _create_session(db, user)
    db.commit()
    return AuthenticatedSession(user=user, token=token)


def get_user_for_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    return user_repository.get_user_by_session_token_hash(db, _hash_session_token(token), datetime.now(UTC))


def logout(db: Session, token: str | None) -> None:
    if token:
        user_repository.delete_auth_session(db, _hash_session_token(token))
        db.commit()


def ensure_bootstrap_admin(db: Session) -> User | None:
    username = settings.bootstrap_admin_username.strip().casefold()
    password = settings.bootstrap_admin_password
    if not username or not password:
        return None

    user = user_repository.get_user_by_username(db, username)
    if user is None:
        user = user_repository.create_user(db, username, password_hash.hash(password))
    else:
        try:
            password_matches = password_hash.verify(password, user.password_hash)
        except Exception:
            password_matches = False
        if not password_matches:
            user_repository.set_user_password_hash(db, user, password_hash.hash(password))

    user_repository.set_user_role(db, user, "admin")
    user.is_active = True
    db.commit()
    db.refresh(user)
    return user
