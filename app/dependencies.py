from collections.abc import AsyncGenerator, Generator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.repositories import retrieval_config_repository
from app.services import auth_service, language_model_service


def get_authenticated_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = auth_service.get_user_for_token(db, request.cookies.get(settings.auth_cookie_name))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


def get_current_user(user: User = Depends(get_authenticated_user)) -> User:
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password change required")
    return user

async def get_current_user_with_language_model(
    user: User = Depends(get_current_user),
) -> AsyncGenerator[User, None]:
    endpoint_key = language_model_service.get_user_endpoint_key(user)
    with language_model_service.use_endpoint(endpoint_key):
        yield user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return user


def ensure_retrieval_writes_available(db: Session = Depends(get_db)) -> None:
    if retrieval_config_repository.get_configuration(db).maintenance_mode:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Retrieval maintenance is in progress",
        )


__all__ = [
    "ensure_retrieval_writes_available",
    "get_authenticated_user",
    "get_current_admin",
    "get_current_user",
    "get_current_user_with_language_model",
    "get_db",
]
