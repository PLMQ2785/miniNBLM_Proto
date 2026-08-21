import re
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.config import LLMEndpointFileEntry
from app.dependencies import get_current_admin
from app.models.user import User
from app.schemas.admin_language_models import (
    AdminLanguageModelEndpointResponse,
    AdminLanguageModelStateResponse,
    LanguageModelEndpointWriteRequest,
)
from app.services import language_model_service
from app.services.language_model_service import (
    LanguageModelConfigurationConflictError,
    LanguageModelConfigurationError,
    LanguageModelEndpointConflictError,
    LanguageModelEndpointIncompatibleError,
    LanguageModelEndpointNotFoundError,
    LanguageModelEndpointUnavailableError,
)
from app.services.language_model_registry import LanguageModelSnapshot


router = APIRouter(prefix="/admin/language-models", tags=["admin-language-models"])


def _expected_revision(
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> str:
    """관리자 수정에 필요한 현재 JSON SHA-256 revision을 검증한다."""
    if if_match is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="If-Match revision is required",
        )
    revision = if_match.strip().strip('"')
    if not re.fullmatch(r"[0-9a-f]{64}", revision):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="If-Match revision is invalid",
        )
    return revision


def _endpoint_response(
    endpoint: LLMEndpointFileEntry,
    default_endpoint_key: str,
) -> AdminLanguageModelEndpointResponse:
    """credential 값 없이 JSON endpoint를 관리자 응답으로 변환한다."""
    if endpoint.api_key_env is not None:
        credential_source = "environment"
        credential_reference = endpoint.api_key_env
    else:
        credential_source = "file"
        credential_reference = endpoint.api_key_file or ""
    return AdminLanguageModelEndpointResponse(
        key=endpoint.key,
        display_name=endpoint.display_name,
        base_url=endpoint.base_url,
        model=endpoint.model,
        supports_vision=endpoint.supports_vision,
        enabled=endpoint.enabled,
        credential_source=credential_source,
        credential_reference=credential_reference,
        is_default=endpoint.key == default_endpoint_key,
    )


def _state_response(
    snapshot: LanguageModelSnapshot | None = None,
) -> AdminLanguageModelStateResponse:
    """현재 정상 JSON snapshot을 비밀 없는 관리자 상태로 묶는다."""
    current = snapshot or language_model_service.get_snapshot()
    return AdminLanguageModelStateResponse(
        revision=current.revision,
        default_endpoint_key=current.configuration.default_endpoint,
        reload_error=language_model_service.get_reload_error(),
        endpoints=[
            _endpoint_response(endpoint, current.configuration.default_endpoint)
            for endpoint in current.configuration.endpoints
        ],
    )


def _entry(request: LanguageModelEndpointWriteRequest) -> LLMEndpointFileEntry:
    """관리자 입력을 JSON 파일 endpoint 계약으로 변환한다."""
    return LLMEndpointFileEntry.model_validate(request.model_dump())


def _raise_service_error(exc: Exception) -> NoReturn:
    """registry와 endpoint 검증 오류를 공개 가능한 HTTP 상태로 변환한다."""
    if isinstance(exc, LanguageModelEndpointNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Language model endpoint not found",
        ) from exc
    if isinstance(
        exc,
        (
            LanguageModelConfigurationConflictError,
            LanguageModelEndpointConflictError,
            LanguageModelEndpointIncompatibleError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if isinstance(exc, LanguageModelEndpointUnavailableError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    if isinstance(exc, LanguageModelConfigurationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    raise exc


@router.get("", response_model=AdminLanguageModelStateResponse)
def get_language_model_admin_state(
    _: User = Depends(get_current_admin),
) -> AdminLanguageModelStateResponse:
    """관리자에게 JSON revision과 활성·비활성 endpoint 전체를 반환한다."""
    return _state_response()


@router.post(
    "",
    response_model=AdminLanguageModelStateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_language_model_endpoint(
    request: LanguageModelEndpointWriteRequest,
    revision: str = Depends(_expected_revision),
    admin: User = Depends(get_current_admin),
) -> AdminLanguageModelStateResponse:
    """새 endpoint를 연결 검증한 뒤 JSON에 원자적으로 추가한다."""
    try:
        snapshot = language_model_service.create_endpoint(
            actor_id=admin.id,
            expected_revision=revision,
            endpoint=_entry(request),
        )
    except Exception as exc:
        _raise_service_error(exc)
    return _state_response(snapshot)


@router.put("/{endpoint_key}", response_model=AdminLanguageModelStateResponse)
def update_language_model_endpoint(
    endpoint_key: str,
    request: LanguageModelEndpointWriteRequest,
    revision: str = Depends(_expected_revision),
    admin: User = Depends(get_current_admin),
) -> AdminLanguageModelStateResponse:
    """endpoint key를 유지하고 검증 성공한 JSON 값만 공개한다."""
    try:
        snapshot = language_model_service.update_endpoint(
            actor_id=admin.id,
            expected_revision=revision,
            endpoint_key=endpoint_key,
            endpoint=_entry(request),
        )
    except Exception as exc:
        _raise_service_error(exc)
    return _state_response(snapshot)


@router.post("/{endpoint_key}/default", response_model=AdminLanguageModelStateResponse)
def set_default_language_model_endpoint(
    endpoint_key: str,
    revision: str = Depends(_expected_revision),
    admin: User = Depends(get_current_admin),
) -> AdminLanguageModelStateResponse:
    """연결 가능한 활성 endpoint를 JSON 기본값으로 변경한다."""
    try:
        snapshot = language_model_service.set_default_endpoint(
            actor_id=admin.id,
            expected_revision=revision,
            endpoint_key=endpoint_key,
        )
    except Exception as exc:
        _raise_service_error(exc)
    return _state_response(snapshot)


@router.delete("/{endpoint_key}", response_model=AdminLanguageModelStateResponse)
def delete_language_model_endpoint(
    endpoint_key: str,
    revision: str = Depends(_expected_revision),
    admin: User = Depends(get_current_admin),
) -> AdminLanguageModelStateResponse:
    """기본값이 아닌 endpoint를 JSON에서 원자적으로 제거한다."""
    try:
        snapshot = language_model_service.delete_endpoint(
            actor_id=admin.id,
            expected_revision=revision,
            endpoint_key=endpoint_key,
        )
    except Exception as exc:
        _raise_service_error(exc)
    return _state_response(snapshot)
