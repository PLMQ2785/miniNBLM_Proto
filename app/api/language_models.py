from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import LLMEndpoint
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
    """내부 엔드포인트 설정을 공개 API 응답으로 변환한다."""
    return LanguageModelEndpointResponse(
        key=endpoint.key,
        display_name=endpoint.display_name,
        model=endpoint.model,
        supports_vision=endpoint.supports_vision,
    )


def _state_response(user: User) -> LanguageModelStateResponse:
    """최신 JSON의 선택 가능 목록과 실제 사용자 endpoint를 묶는다."""
    return LanguageModelStateResponse(
        endpoints=[
            _endpoint_response(endpoint)
            for endpoint in language_model_service.list_enabled_endpoints()
        ],
        active_endpoint_key=language_model_service.get_user_endpoint_key(user),
    )


@router.get("", response_model=LanguageModelStateResponse)
def get_language_model_state(
    user: User = Depends(get_current_user),
) -> LanguageModelStateResponse:
    """현재 사용자가 선택할 수 있는 모델과 활성 모델을 반환한다."""
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
    """모델 호환성과 가용성을 확인한 뒤 사용자 선택을 저장한다."""
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
