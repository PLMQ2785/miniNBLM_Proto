from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.auth import AuthResponse, LoginCredentials, RegistrationCredentials, UserResponse
from app.services import auth_service
from app.services.auth_service import InvalidCredentialsError, UsernameAlreadyExistsError

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_response(user: User) -> UserResponse:
    return UserResponse(user_id=user.public_id, username=user.username, role=user.role)


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
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=AuthResponse)
def me(response: Response, user: User = Depends(get_current_user)) -> AuthResponse:
    response.headers["Cache-Control"] = "no-store"
    return AuthResponse(user=_user_response(user))
