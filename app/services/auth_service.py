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
    """가입하려는 사용자명이 이미 존재할 때 발생한다."""
    pass


class InvalidCredentialsError(Exception):
    """로그인 자격 증명이 유효하지 않을 때 발생한다."""
    pass


class InvalidCurrentPasswordError(Exception):
    """본인 확인용 현재 비밀번호가 틀릴 때 발생한다."""
    pass


class PasswordReuseError(Exception):
    """새 비밀번호가 기존 비밀번호와 같을 때 발생한다."""
    pass


class AccountConfirmationError(Exception):
    """계정 삭제 확인 사용자명이 일치하지 않을 때 발생한다."""
    pass


class AccountDeletionConflictError(Exception):
    """처리 중 문서 때문에 계정을 안전하게 지울 수 없을 때 발생한다."""
    pass


class UserNotFoundError(Exception):
    """관리자가 초기화할 활성 사용자를 찾지 못했을 때 발생한다."""
    pass


class SelfPasswordResetError(Exception):
    """관리자가 자신의 비밀번호를 초기화하려 할 때 발생한다."""
    pass


@dataclass(frozen=True)
class AuthenticatedSession:
    """인증 API가 사용자와 원문 세션 토큰을 함께 전달할 때 쓴다."""
    user: User
    token: str


password_hash = PasswordHash.recommended()
dummy_password_hash = password_hash.hash("not-a-real-user-password")
logger = logging.getLogger(__name__)
ACTIVE_DOCUMENT_STATUSES = {"uploaded", "processing"}


def _hash_session_token(token: str) -> str:
    """원문 세션 토큰을 저장·조회용 SHA-256 해시로 바꾼다."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_session(db: Session, user: User) -> str:
    """사용자 세션을 만들고 브라우저에 줄 원문 토큰을 반환한다."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=settings.auth_session_ttl_hours)
    user_repository.create_auth_session(db, user.id, _hash_session_token(token), expires_at)
    return token


def register(db: Session, username: str, password: str) -> AuthenticatedSession:
    """사용자를 등록하고 첫 인증 세션까지 하나의 트랜잭션으로 커밋한다."""
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
    """자격 증명을 검증하고 새 인증 세션을 커밋한다."""
    user = user_repository.get_user_by_username(db, username)
    # 미등록 사용자도 실제 해시를 검증해 사용자명 추측 시간차를 줄인다.
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
    """유효한 세션 토큰에 연결된 활성 사용자를 조회한다."""
    if not token:
        return None
    return user_repository.get_user_by_session_token_hash(db, _hash_session_token(token), datetime.now(UTC))


def logout(db: Session, token: str | None) -> None:
    """현재 세션 토큰을 삭제하고 즉시 커밋한다."""
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
    """비밀번호를 바꾸고 현재 세션 외 인증을 한 트랜잭션에서 폐기한다."""
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
    """관리자가 임시 비밀번호를 설정하고 모든 기존 세션을 폐기한다."""
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
    """본인 확인 뒤 계정 소유 데이터와 파일을 안전하게 삭제한다."""
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
    """시작 설정의 관리자 계정을 생성·승격하고 변경 의무를 적용한다."""
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
