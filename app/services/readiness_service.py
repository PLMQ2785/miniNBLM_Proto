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
    """의존 서비스 응답이 준비 상태 계약과 다름을 표시한다."""
    pass


@dataclass(frozen=True)
class ComponentCheck:
    """준비 상태 점검 이름과 실행 함수를 병렬 실행기에 묶어 전달한다."""
    name: str
    check: Callable[[float], None]


def check_readiness(timeout: float | None = None) -> ReadinessResponse:
    """DB·임베딩·LLM을 병렬 점검해 전체 준비 상태를 구성한다."""
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
    """개별 점검의 실패를 안전한 상세와 지연 시간이 담긴 결과로 바꾼다."""
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
    """별도 일회성 연결로 제한 시간 안에 DB 쿼리가 가능한지 확인한다."""
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
    """임베딩 서버의 헬스 응답이 정상 계약을 만족하는지 확인한다."""
    response = httpx.get(
        f"{settings.embedding_base_url.rstrip('/')}/health",
        timeout=timeout,
    )
    response.raise_for_status()
    if response.json().get("status") != "ok":
        raise InvalidComponentResponseError("Unexpected health response")


def _check_llm(timeout: float) -> None:
    """설정한 LLM 엔드포인트가 대상 모델을 실제 제공하는지 확인한다."""
    endpoint = settings.get_llm_endpoint()
    response = httpx.get(
        f"{endpoint.base_url}/models",
        headers={"Authorization": f"Bearer {endpoint.api_key}"},
        timeout=timeout,
    )
    response.raise_for_status()
    model_ids = {item.get("id") for item in response.json().get("data", [])}
    if endpoint.model not in model_ids:
        raise InvalidComponentResponseError("Configured model is not served")


def _safe_error_detail(exc: Exception) -> str:
    """내부 예외를 자격 증명이 드러나지 않는 준비 상태 설명으로 축약한다."""
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
    """점검 시작 시점부터 흐른 시간을 밀리초로 계산한다."""
    return max(0, round((monotonic() - started_at) * 1000))
