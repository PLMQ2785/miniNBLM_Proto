from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from math import ceil
from time import monotonic

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.config import settings
from app.schemas.health import ReadinessComponent, ReadinessResponse


class InvalidComponentResponseError(Exception):
    pass


@dataclass(frozen=True)
class ComponentCheck:
    name: str
    check: Callable[[float], None]


def check_readiness(timeout: float | None = None) -> ReadinessResponse:
    check_timeout = timeout or settings.readiness_timeout_seconds
    checks = (
        ComponentCheck("database", _check_database),
        ComponentCheck("embedding", _check_embedding),
        ComponentCheck("llm", _check_llm),
    )
    with ThreadPoolExecutor(max_workers=len(checks), thread_name_prefix="readiness") as executor:
        futures = {
            check.name: executor.submit(_run_check, check.check, check_timeout)
            for check in checks
        }
        components = {name: future.result() for name, future in futures.items()}

    ready = all(component.status == "ok" for component in components.values())
    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        components=components,
    )


def _run_check(check: Callable[[float], None], timeout: float) -> ReadinessComponent:
    started_at = monotonic()
    try:
        check(timeout)
    except Exception as exc:
        return ReadinessComponent(
            status="error",
            latency_ms=_elapsed_ms(started_at),
            detail=_safe_error_detail(exc),
        )
    return ReadinessComponent(status="ok", latency_ms=_elapsed_ms(started_at))


def _check_database(timeout: float) -> None:
    timeout_ms = max(1, int(timeout * 1000))
    readiness_engine = create_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args={"connect_timeout": max(1, ceil(timeout))},
    )
    try:
        with readiness_engine.connect() as connection:
            connection.execute(
                text("SELECT set_config('statement_timeout', :timeout, true)"),
                {"timeout": f"{timeout_ms}ms"},
            )
            connection.execute(text("SELECT 1"))
    finally:
        readiness_engine.dispose()


def _check_embedding(timeout: float) -> None:
    response = httpx.get(
        f"{settings.embedding_base_url.rstrip('/')}/health",
        timeout=timeout,
    )
    response.raise_for_status()
    if response.json().get("status") != "ok":
        raise InvalidComponentResponseError("Unexpected health response")


def _check_llm(timeout: float) -> None:
    response = httpx.get(
        f"{settings.vllm_base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {settings.vllm_api_key}"},
        timeout=timeout,
    )
    response.raise_for_status()
    model_ids = {item.get("id") for item in response.json().get("data", [])}
    if settings.vllm_model not in model_ids:
        raise InvalidComponentResponseError("Configured model is not served")


def _safe_error_detail(exc: Exception) -> str:
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "Timed out"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return "Connection failed"
    if isinstance(exc, SQLAlchemyError):
        return "Database query failed"
    if isinstance(exc, InvalidComponentResponseError):
        return str(exc)
    return "Unexpected check failure"


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((monotonic() - started_at) * 1000))
