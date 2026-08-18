from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_admin, get_db
from app.models.user import User
from app.password_policy import PasswordPolicyError
from app.schemas.auth import AdminPasswordResetRequest, UserResponse
from app.services import auth_service
from app.services.auth_service import PasswordReuseError, SelfPasswordResetError, UserNotFoundError

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


@router.post("/password-reset", response_model=UserResponse)
def reset_user_password(
    request: AdminPasswordResetRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> UserResponse:
    try:
        user = auth_service.reset_password(
            db,
            admin,
            request.username,
            request.temporary_password,
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
    except SelfPasswordResetError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Use the account password change flow for your own account",
        ) from exc
    except PasswordReuseError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Temporary password must be different",
        ) from exc
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return UserResponse(
        user_id=user.public_id,
        username=user.username,
        role=user.role,
        must_change_password=user.must_change_password,
    )
