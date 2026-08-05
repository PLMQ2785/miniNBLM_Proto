import pytest
from fastapi.testclient import TestClient

from app.api import health as health_api
from app.schemas.health import ReadinessComponent, ReadinessResponse


pytestmark = pytest.mark.integration


def _readiness(status: str) -> ReadinessResponse:
    component_status = "ok" if status == "ready" else "error"
    return ReadinessResponse(
        status=status,
        components={
            "database": ReadinessComponent(status="ok", latency_ms=1),
            "embedding": ReadinessComponent(status=component_status, latency_ms=2),
            "llm": ReadinessComponent(status="ok", latency_ms=3),
        },
    )


def test_liveness_does_not_depend_on_external_services(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_200_when_all_components_are_ready(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health_api, "check_readiness", lambda: _readiness("ready"))

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["components"]["embedding"]["status"] == "ok"


def test_readiness_returns_503_with_component_details(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health_api, "check_readiness", lambda: _readiness("not_ready"))

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["components"]["embedding"]["status"] == "error"
