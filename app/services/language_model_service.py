import logging
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator

import httpx
from sqlalchemy.orm import Session

from app.config import LLMEndpoint, settings
from app.models.user import User


logger = logging.getLogger(__name__)
# Keeps concurrent requests from leaking a user's model choice into each other.
active_endpoint_context: ContextVar[str | None] = ContextVar(
    "active_llm_endpoint",
    default=None,
)


class LanguageModelEndpointNotFoundError(Exception):
    pass


class LanguageModelEndpointUnavailableError(Exception):
    pass


class LanguageModelEndpointIncompatibleError(Exception):
    pass


def get_user_endpoint_key(user: User) -> str:
    endpoint_key = user.active_llm_endpoint_key or settings.llm_default_endpoint
    try:
        settings.get_llm_endpoint(endpoint_key)
    except KeyError:
        logger.warning(
            "User LLM endpoint is no longer configured; using environment default: "
            "user_id=%s stored=%s default=%s",
            user.id,
            endpoint_key,
            settings.llm_default_endpoint,
        )
        return settings.llm_default_endpoint
    return endpoint_key


def get_active_endpoint() -> LLMEndpoint:
    endpoint_key = active_endpoint_context.get() or settings.llm_default_endpoint
    try:
        return settings.get_llm_endpoint(endpoint_key)
    except KeyError:
        logger.error(
            "Context LLM endpoint is not configured; using environment default: "
            "active=%s default=%s",
            endpoint_key,
            settings.llm_default_endpoint,
        )
        return settings.get_llm_endpoint(settings.llm_default_endpoint)


@contextmanager
def use_endpoint(endpoint_key: str) -> Iterator[None]:
    token = active_endpoint_context.set(endpoint_key)
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
    try:
        endpoint = settings.get_llm_endpoint(endpoint_key)
    except KeyError as exc:
        raise LanguageModelEndpointNotFoundError from exc

    if settings.vision_caption_mode != "disabled" and not endpoint.supports_vision:
        raise LanguageModelEndpointIncompatibleError(
            "Vision captioning requires a vision-capable language model"
        )

    _verify_endpoint(endpoint)
    user.active_llm_endpoint_key = endpoint.key
    db.commit()
    db.refresh(user)
    return user


def _verify_endpoint(endpoint: LLMEndpoint) -> None:
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
