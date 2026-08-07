from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import (
    ensure_retrieval_writes_available,
    get_authenticated_user,
    get_current_user,
    get_db,
)
from app.models.user import User
from app.password_policy import PasswordPolicyError
from app.schemas.auth import (
    AuthResponse,
    AccountDeleteRequest,
    LoginCredentials,
    PasswordChangeRequest,
    RegistrationCredentials,
    UserResponse,
)
from app.services import auth_service
from app.services.auth_service import (
    AccountConfirmationError,
    AccountDeletionConflictError,
    InvalidCredentialsError,
    InvalidCurrentPasswordError,
    PasswordReuseError,
    UsernameAlreadyExistsError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        user_id=user.public_id,
        username=user.username,
        role=user.role,
        must_change_password=user.must_change_password,
    )


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.auth_session_ttl_hours * 60 * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    credentials: RegistrationCredentials,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthResponse:
    try:
        authenticated = auth_service.register(db, credentials.username, credentials.password)
    except UsernameAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists") from exc
    _set_session_cookie(response, authenticated.token)
    return AuthResponse(user=_user_response(authenticated.user))


@router.post("/login", response_model=AuthResponse)
def login(credentials: LoginCredentials, response: Response, db: Session = Depends(get_db)) -> AuthResponse:
    try:
        authenticated = auth_service.login(db, credentials.username, credentials.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password") from exc
    _set_session_cookie(response, authenticated.token)
    return AuthResponse(user=_user_response(authenticated.user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    auth_service.logout(db, request.cookies.get(settings.auth_cookie_name))
    _clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/password", response_model=AuthResponse)
def change_password(
    credentials: PasswordChangeRequest,
    request: Request,
    response: Response,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
) -> AuthResponse:
    session_token = request.cookies.get(settings.auth_cookie_name)
    if session_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    try:
        updated_user = auth_service.change_password(
            db,
            user,
            credentials.current_password,
            credentials.new_password,
            session_token,
        )
    except InvalidCurrentPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        ) from exc
    except PasswordReuseError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="New password must be different") from exc
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return AuthResponse(user=_user_response(updated_user))


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    credentials: AccountDeleteRequest,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(ensure_retrieval_writes_available),
) -> Response:
    try:
        auth_service.delete_account(
            db,
            user,
            credentials.current_password,
            credentials.username_confirmation,
        )
    except InvalidCurrentPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        ) from exc
    except AccountConfirmationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username confirmation does not match",
        ) from exc
    except AccountDeletionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account cannot be deleted while documents are processing",
        ) from exc

    _clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=AuthResponse)
def me(response: Response, user: User = Depends(get_authenticated_user)) -> AuthResponse:
    response.headers["Cache-Control"] = "no-store"
    return AuthResponse(user=_user_response(user))
