import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User
from app.password_policy import validate_secure_password
from app.repositories import user_repository
from app.storage.local_storage import LocalStorage


class UsernameAlreadyExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InvalidCurrentPasswordError(Exception):
    pass


class PasswordReuseError(Exception):
    pass


class AccountConfirmationError(Exception):
    pass


class AccountDeletionConflictError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


class SelfPasswordResetError(Exception):
    pass


@dataclass(frozen=True)
class AuthenticatedSession:
    user: User
    token: str


password_hash = PasswordHash.recommended()
dummy_password_hash = password_hash.hash("not-a-real-user-password")
logger = logging.getLogger(__name__)
ACTIVE_DOCUMENT_STATUSES = {"uploaded", "processing"}


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


def change_password(
    db: Session,
    user: User,
    current_password: str,
    new_password: str,
    session_token: str,
) -> User:
    try:
        current_password_valid = password_hash.verify(current_password, user.password_hash)
    except Exception:
        current_password_valid = False
    if not current_password_valid:
        raise InvalidCurrentPasswordError

    validate_secure_password(new_password, user.username)
    try:
        password_reused = password_hash.verify(new_password, user.password_hash)
    except Exception:
        password_reused = False
    if password_reused:
        raise PasswordReuseError

    user_repository.set_user_password_hash(db, user, password_hash.hash(new_password))
    user_repository.set_password_change_required(db, user, False)
    user_repository.delete_other_auth_sessions(db, user.id, _hash_session_token(session_token))
    db.commit()
    db.refresh(user)
    return user


def reset_password(
    db: Session,
    admin: User,
    username: str,
    temporary_password: str,
) -> User:
    user = user_repository.get_user_by_username(db, username)
    if user is None or not user.is_active:
        raise UserNotFoundError
    if user.id == admin.id:
        raise SelfPasswordResetError

    validate_secure_password(temporary_password, user.username)
    try:
        password_reused = password_hash.verify(temporary_password, user.password_hash)
    except Exception:
        password_reused = False
    if password_reused:
        raise PasswordReuseError

    user_repository.set_user_password_hash(db, user, password_hash.hash(temporary_password))
    user_repository.set_password_change_required(db, user, True)
    user_repository.delete_auth_sessions_for_user(db, user.id)
    db.commit()
    db.refresh(user)
    return user


def delete_account(
    db: Session,
    user: User,
    current_password: str,
    username_confirmation: str,
) -> None:
    try:
        current_password_valid = password_hash.verify(current_password, user.password_hash)
    except Exception:
        current_password_valid = False
    if not current_password_valid:
        raise InvalidCurrentPasswordError
    if username_confirmation.strip().casefold() != user.username:
        raise AccountConfirmationError

    documents = user_repository.list_owned_documents_for_update(db, user.id)
    if any(status in ACTIVE_DOCUMENT_STATUSES for _, status in documents):
        raise AccountDeletionConflictError

    document_ids = [document_id for document_id, _ in documents]
    user_repository.delete_user_and_owned_data(db, user, document_ids)
    db.commit()

    storage = LocalStorage()
    for document_id in document_ids:
        try:
            storage.delete_document(document_id)
        except OSError:
            logger.exception(
                "Failed to remove files after account deletion for document_id=%s",
                document_id,
            )


def ensure_bootstrap_admin(db: Session) -> User | None:
    username = settings.bootstrap_admin_username
    password = settings.bootstrap_admin_password
    if username is None or password is None:
        return None

    user = user_repository.get_user_by_username(db, username)
    if user is None:
        user = user_repository.create_user(
            db,
            username,
            password_hash.hash(password),
            must_change_password=True,
        )
    elif user.role != "admin":
        try:
            password_matches = password_hash.verify(password, user.password_hash)
        except Exception:
            password_matches = False
        if not password_matches:
            raise RuntimeError(
                "Bootstrap administrator username belongs to an existing account with a different password"
            )
        user_repository.set_password_change_required(db, user, True)

    user_repository.set_user_role(db, user, "admin")
    user.is_active = True
    db.commit()
    db.refresh(user)
    return user
