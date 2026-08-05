import httpx
import pytest
from sqlalchemy.exc import OperationalError

from app.services import readiness_service


def test_all_components_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness_service, "_check_database", lambda timeout: None)
    monkeypatch.setattr(readiness_service, "_check_embedding", lambda timeout: None)
    monkeypatch.setattr(readiness_service, "_check_llm", lambda timeout: None)

    result = readiness_service.check_readiness(timeout=0.1)

    assert result.status == "ready"
    assert set(result.components) == {"database", "embedding", "llm"}
    assert all(component.status == "ok" for component in result.components.values())


def test_timeout_and_database_errors_are_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("GET", "http://embedding/health")

    def timeout(_: float) -> None:
        raise httpx.ReadTimeout("secret internal URL", request=request)

    def database_error(_: float) -> None:
        raise OperationalError("SELECT 1", {}, Exception("secret DSN"))

    monkeypatch.setattr(readiness_service, "_check_database", database_error)
    monkeypatch.setattr(readiness_service, "_check_embedding", timeout)
    monkeypatch.setattr(readiness_service, "_check_llm", lambda check_timeout: None)

    result = readiness_service.check_readiness(timeout=0.1)

    assert result.status == "not_ready"
    assert result.components["database"].detail == "Database query failed"
    assert result.components["embedding"].detail == "Timed out"
    assert result.components["llm"].status == "ok"


def test_llm_check_requires_the_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "http://llm/v1/models"),
        json={"data": [{"id": "another-model"}]},
    )
    monkeypatch.setattr(readiness_service.httpx, "get", lambda *args, **kwargs: response)

    component = readiness_service._run_check(readiness_service._check_llm, 0.1)

    assert component.status == "error"
    assert component.detail == "Configured model is not served"


def test_http_status_error_exposes_only_the_status_code() -> None:
    request = httpx.Request("GET", "http://internal-service/health")
    response = httpx.Response(503, request=request)

    def unavailable(_: float) -> None:
        response.raise_for_status()

    component = readiness_service._run_check(unavailable, 0.1)

    assert component.status == "error"
    assert component.latency_ms >= 0
    assert component.detail == "HTTP 503"
