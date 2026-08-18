from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import LLMEndpoint, settings
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.language_models import (
    LanguageModelEndpointResponse,
    LanguageModelStateResponse,
)
from app.services import language_model_service
from app.services.language_model_service import (
    LanguageModelEndpointIncompatibleError,
    LanguageModelEndpointNotFoundError,
    LanguageModelEndpointUnavailableError,
)


router = APIRouter(prefix="/language-models", tags=["language-models"])


def _endpoint_response(endpoint: LLMEndpoint) -> LanguageModelEndpointResponse:
    return LanguageModelEndpointResponse(
        key=endpoint.key,
        display_name=endpoint.display_name,
        model=endpoint.model,
        supports_vision=endpoint.supports_vision,
    )


def _state_response(user: User) -> LanguageModelStateResponse:
    return LanguageModelStateResponse(
        endpoints=[_endpoint_response(endpoint) for endpoint in settings.llm_endpoints],
        active_endpoint_key=language_model_service.get_user_endpoint_key(user),
    )


@router.get("", response_model=LanguageModelStateResponse)
def get_language_model_state(
    user: User = Depends(get_current_user),
) -> LanguageModelStateResponse:
    return _state_response(user)


@router.post(
    "/{endpoint_key}/activate",
    response_model=LanguageModelStateResponse,
)
def activate_language_model(
    endpoint_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LanguageModelStateResponse:
    try:
        language_model_service.activate_endpoint(
            db,
            endpoint_key=endpoint_key,
            user=user,
        )
    except LanguageModelEndpointNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Language model endpoint not found",
        ) from exc
    except LanguageModelEndpointIncompatibleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except LanguageModelEndpointUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return _state_response(user)
