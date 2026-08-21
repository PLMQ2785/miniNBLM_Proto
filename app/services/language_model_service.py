import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import httpx
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import LLMConfigurationFile, LLMEndpoint, LLMEndpointFileEntry, settings
from app.models.user import User
from app.services.language_model_registry import (
    LanguageModelConfigurationConflictError,
    LanguageModelConfigurationError,
    LanguageModelRegistry,
    LanguageModelSnapshot,
)


logger = logging.getLogger(__name__)
# 설정 변경 중에도 한 요청의 모든 하위 호출은 같은 endpoint snapshot을 쓴다.
active_endpoint_context: ContextVar[LLMEndpoint | None] = ContextVar(
    "active_llm_endpoint",
    default=None,
)
registry = LanguageModelRegistry(
    settings.llm_endpoints_file,
    settings.llm_secrets_dir,
    vision_caption_mode=settings.vision_caption_mode,
)


class LanguageModelEndpointNotFoundError(Exception):
    """요청한 모델 endpoint가 현재 JSON에 없음을 나타낸다."""


class LanguageModelEndpointUnavailableError(Exception):
    """선택한 모델 서버나 모델을 사용할 수 없음을 나타낸다."""


class LanguageModelEndpointIncompatibleError(Exception):
    """현재 런타임 기능과 모델 endpoint가 맞지 않음을 나타낸다."""


class LanguageModelEndpointConflictError(Exception):
    """중복 key나 기본 endpoint 보호로 변경할 수 없음을 나타낸다."""


def initialize_configuration() -> None:
    """요청 수신 전에 JSON 원본과 모든 credential 참조를 검증한다."""
    registry.initialize()


def get_snapshot() -> LanguageModelSnapshot:
    """파일 변경을 lazy reload한 최신 정상 endpoint snapshot을 반환한다."""
    return registry.snapshot()


def get_reload_error() -> str | None:
    """외부 JSON 변경이 거부된 최근 원인을 관리자 상태에 제공한다."""
    return registry.reload_error


def list_enabled_endpoints() -> tuple[LLMEndpoint, ...]:
    """사용자가 선택할 수 있는 최신 활성 endpoint 목록을 반환한다."""
    return get_snapshot().enabled_endpoints


def get_user_endpoint(user: User) -> LLMEndpoint:
    """저장된 사용자 선택이 사라지거나 비활성이면 현재 기본값으로 돌아간다."""
    snapshot = get_snapshot()
    if user.active_llm_endpoint_key:
        try:
            return snapshot.get_endpoint(user.active_llm_endpoint_key, enabled_only=True)
        except KeyError:
            logger.warning(
                "User LLM endpoint is unavailable; using JSON default: user_id=%s stored=%s default=%s",
                user.id,
                user.active_llm_endpoint_key,
                snapshot.default_endpoint.key,
            )
    return snapshot.default_endpoint


def get_user_endpoint_key(user: User) -> str:
    """사용자에게 다음 요청부터 실제 적용되는 endpoint key를 반환한다."""
    return get_user_endpoint(user).key


def get_active_endpoint() -> LLMEndpoint:
    """요청 snapshot을 우선하고 요청 밖 호출에는 최신 JSON 기본값을 쓴다."""
    return active_endpoint_context.get() or get_snapshot().default_endpoint


@contextmanager
def use_endpoint(endpoint: LLMEndpoint) -> Iterator[None]:
    """하위 모델 호출 동안 immutable endpoint snapshot을 문맥에 고정한다."""
    token = active_endpoint_context.set(endpoint)
    try:
        yield
    finally:
        active_endpoint_context.reset(token)


def activate_endpoint(
    db: Session,
    *,
    user: User,
    endpoint_key: str,
) -> User:
    """최신 JSON endpoint의 호환성과 연결을 확인하고 사용자 선택을 저장한다."""
    try:
        endpoint = get_snapshot().get_endpoint(endpoint_key, enabled_only=True)
    except KeyError as exc:
        raise LanguageModelEndpointNotFoundError from exc
    _require_vision_compatibility(endpoint)
    verify_endpoint(endpoint)
    user.active_llm_endpoint_key = endpoint.key
    db.commit()
    db.refresh(user)
    return user


def verify_endpoint(endpoint: LLMEndpoint) -> None:
    """모델 서버가 설정한 model ID를 실제로 제공하는지 확인한다."""
    try:
        response = httpx.get(
            f"{endpoint.base_url}/models",
            headers={"Authorization": f"Bearer {endpoint.api_key}"},
            timeout=settings.readiness_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        models = payload.get("data")
        if not isinstance(models, list):
            raise ValueError("Invalid model list")
        model_ids = {
            item.get("id")
            for item in models
            if isinstance(item, dict)
        }
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        raise LanguageModelEndpointUnavailableError(
            "Selected language model endpoint is unavailable"
        ) from exc
    if endpoint.model not in model_ids:
        raise LanguageModelEndpointUnavailableError(
            "Selected endpoint does not serve the configured model"
        )


def create_endpoint(
    *,
    actor_id: int,
    expected_revision: str,
    endpoint: LLMEndpointFileEntry,
) -> LanguageModelSnapshot:
    """새 endpoint를 검증한 뒤 JSON에 원자적으로 추가한다."""
    current = get_snapshot().configuration
    if current.get_endpoint(endpoint.key) is not None:
        raise LanguageModelEndpointConflictError("Language model endpoint key already exists")
    candidate = _configuration(
        default_endpoint=current.default_endpoint,
        endpoints=(*current.endpoints, endpoint),
    )
    snapshot = registry.replace(
        candidate,
        expected_revision=expected_revision,
        validate=lambda value: _verify_changed_endpoint(value, endpoint.key),
    )
    _log_admin_change(actor_id, "create", endpoint.key, snapshot.revision)
    return snapshot


def update_endpoint(
    *,
    actor_id: int,
    expected_revision: str,
    endpoint_key: str,
    endpoint: LLMEndpointFileEntry,
) -> LanguageModelSnapshot:
    """key는 유지하고 검증된 endpoint 값만 JSON에 반영한다."""
    current = get_snapshot().configuration
    if current.get_endpoint(endpoint_key) is None:
        raise LanguageModelEndpointNotFoundError
    if endpoint.key != endpoint_key:
        raise LanguageModelEndpointConflictError("Language model endpoint key cannot be changed")
    candidate = _configuration(
        default_endpoint=current.default_endpoint,
        endpoints=tuple(endpoint if item.key == endpoint_key else item for item in current.endpoints),
    )
    snapshot = registry.replace(
        candidate,
        expected_revision=expected_revision,
        validate=lambda value: _verify_changed_endpoint(value, endpoint_key),
    )
    _log_admin_change(actor_id, "update", endpoint_key, snapshot.revision)
    return snapshot


def set_default_endpoint(
    *,
    actor_id: int,
    expected_revision: str,
    endpoint_key: str,
) -> LanguageModelSnapshot:
    """활성·연결 가능한 endpoint를 JSON 기본값으로 지정한다."""
    current = get_snapshot().configuration
    endpoint = current.get_endpoint(endpoint_key)
    if endpoint is None:
        raise LanguageModelEndpointNotFoundError
    if not endpoint.enabled:
        raise LanguageModelEndpointConflictError("Disabled endpoint cannot be the default")
    candidate = _configuration(
        default_endpoint=endpoint_key,
        endpoints=current.endpoints,
    )
    snapshot = registry.replace(
        candidate,
        expected_revision=expected_revision,
        validate=lambda value: verify_endpoint(value.get_endpoint(endpoint_key, enabled_only=True)),
    )
    _log_admin_change(actor_id, "set_default", endpoint_key, snapshot.revision)
    return snapshot


def delete_endpoint(
    *,
    actor_id: int,
    expected_revision: str,
    endpoint_key: str,
) -> LanguageModelSnapshot:
    """기본값이 아닌 endpoint를 JSON에서 제거한다."""
    current = get_snapshot().configuration
    if current.get_endpoint(endpoint_key) is None:
        raise LanguageModelEndpointNotFoundError
    if current.default_endpoint == endpoint_key:
        raise LanguageModelEndpointConflictError("Default endpoint cannot be deleted")
    candidate = _configuration(
        default_endpoint=current.default_endpoint,
        endpoints=tuple(item for item in current.endpoints if item.key != endpoint_key),
    )
    snapshot = registry.replace(candidate, expected_revision=expected_revision)
    _log_admin_change(actor_id, "delete", endpoint_key, snapshot.revision)
    return snapshot


def _configuration(
    *,
    default_endpoint: str,
    endpoints: tuple[LLMEndpointFileEntry, ...],
) -> LLMConfigurationFile:
    """관리자 변경 결과를 전체 파일 계약으로 다시 검증한다."""
    try:
        return LLMConfigurationFile.model_validate(
            {"default_endpoint": default_endpoint, "endpoints": endpoints}
        )
    except ValidationError as exc:
        raise LanguageModelConfigurationError(str(exc)) from exc


def _verify_changed_endpoint(snapshot: LanguageModelSnapshot, endpoint_key: str) -> None:
    """활성 endpoint 변경은 publish 전에 실제 연결까지 확인한다."""
    endpoint = snapshot.get_endpoint(endpoint_key)
    if endpoint.enabled:
        _require_vision_compatibility(endpoint)
        verify_endpoint(endpoint)


def _require_vision_compatibility(endpoint: LLMEndpoint) -> None:
    """Vision caption 사용 중에는 비전 미지원 사용자·기본 endpoint를 막는다."""
    if settings.vision_caption_mode != "disabled" and not endpoint.supports_vision:
        raise LanguageModelEndpointIncompatibleError(
            "Vision captioning requires a vision-capable language model"
        )


def _log_admin_change(actor_id: int, action: str, endpoint_key: str, revision: str) -> None:
    """credential을 제외한 관리자 JSON 변경을 구조화 로그로 남긴다."""
    logger.info(
        "Administrator changed language model endpoints: actor_id=%s action=%s endpoint=%s revision=%s",
        actor_id,
        action,
        endpoint_key,
        revision,
    )


__all__ = [
    "LanguageModelConfigurationConflictError",
    "LanguageModelConfigurationError",
    "LanguageModelEndpointConflictError",
    "LanguageModelEndpointIncompatibleError",
    "LanguageModelEndpointNotFoundError",
    "LanguageModelEndpointUnavailableError",
]
