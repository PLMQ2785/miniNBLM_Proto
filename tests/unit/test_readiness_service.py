from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy.exc import OperationalError

from app.config import LLMEndpoint
from app.services import readiness_service


def test_all_components_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """모든 의존 서비스가 응답하면 전체 준비 상태를 ready로 보고한다."""
    monkeypatch.setattr(readiness_service, "_check_database", lambda timeout: None)
    monkeypatch.setattr(readiness_service, "_check_embedding", lambda timeout: None)
    monkeypatch.setattr(readiness_service, "_check_llm", lambda timeout: None)

    result = readiness_service.check_readiness(timeout=0.1)

    assert result.status == "ready"
    assert set(result.components) == {"database", "embedding", "llm"}
    assert all(component.status == "ok" for component in result.components.values())


def test_timeout_and_database_errors_are_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    """상태 점검 오류에서는 내부 URL과 DSN을 노출하지 않는다."""
    request = httpx.Request("GET", "http://embedding/health")

    def timeout(_: float) -> None:
        """내부 주소가 담긴 임베딩 시간 초과를 일으킨다."""
        raise httpx.ReadTimeout("secret internal URL", request=request)

    def database_error(_: float) -> None:
        """민감한 DSN이 담긴 데이터베이스 오류를 일으킨다."""
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
    """LLM 준비 상태는 설정된 모델이 실제 제공될 때만 성공한다."""
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "http://llm/v1/models"),
        json={"data": [{"id": "another-model"}]},
    )
    endpoint = LLMEndpoint(
        key="primary",
        display_name="Primary",
        base_url="http://llm/v1",
        api_key="key",
        model="configured-model",
    )
    monkeypatch.setattr(
        readiness_service.language_model_service,
        "get_snapshot",
        lambda: SimpleNamespace(default_endpoint=endpoint),
    )
    monkeypatch.setattr(readiness_service.httpx, "get", lambda *args, **kwargs: response)

    component = readiness_service._run_check(readiness_service._check_llm, 0.1)

    assert component.status == "error"
    assert component.detail == "Configured model is not served"


def test_http_status_error_exposes_only_the_status_code() -> None:
    """HTTP 점검 실패는 내부 주소 없이 상태 코드만 공개한다."""
    request = httpx.Request("GET", "http://internal-service/health")
    response = httpx.Response(503, request=request)

    def unavailable(_: float) -> None:
        """준비되지 않은 서비스의 HTTP 상태 오류를 일으킨다."""
        response.raise_for_status()

    component = readiness_service._run_check(unavailable, 0.1)

    assert component.status == "error"
    assert component.latency_ms >= 0
    assert component.detail == "HTTP 503"
