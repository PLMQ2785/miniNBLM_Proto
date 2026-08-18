import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import language_models
from app.config import LLMConfiguration, LLMEndpoint
from app.repositories import user_repository


pytestmark = pytest.mark.integration


def _endpoints() -> list[LLMEndpoint]:
    return [
        LLMEndpoint(
            key="primary",
            display_name="Primary model",
            base_url="http://primary:8010/v1",
            api_key="key-a",
            model="model-a",
            supports_vision=False,
        ),
        LLMEndpoint(
            key="secondary",
            display_name="Secondary model",
            base_url="http://secondary:8010/v1",
            api_key="key-b",
            model="model-b",
            supports_vision=True,
        ),
    ]


def _configure_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        language_models.settings,
        "llm_configuration",
        LLMConfiguration(default_endpoint="primary", endpoints=_endpoints()),
    )


def test_language_models_require_login_and_are_available_to_regular_users(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_endpoints(monkeypatch)
    assert client.get("/language-models").status_code == 401

    assert client.post(
        "/auth/register",
        json={"username": "student", "password": "password123"},
    ).status_code == 201
    response = client.get("/language-models")

    assert response.status_code == 200
    assert response.json()["active_endpoint_key"] == "primary"
    assert [endpoint["key"] for endpoint in response.json()["endpoints"]] == [
        "primary",
        "secondary",
    ]


def test_user_activates_available_language_model(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_endpoints(monkeypatch)
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "http://secondary:8010/v1/models"),
        json={"data": [{"id": "model-b"}]},
    )
    monkeypatch.setattr(
        "app.services.language_model_service.httpx.get",
        lambda *args, **kwargs: response,
    )
    assert client.post(
        "/auth/register",
        json={"username": "student", "password": "password123"},
    ).status_code == 201

    activated = client.post("/language-models/secondary/activate")

    assert activated.status_code == 200
    assert activated.json()["active_endpoint_key"] == "secondary"
    db.expire_all()
    assert user_repository.get_user_by_username(db, "student").active_llm_endpoint_key == "secondary"


def test_language_model_selection_is_per_user(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_endpoints(monkeypatch)
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "http://secondary:8010/v1/models"),
        json={"data": [{"id": "model-b"}]},
    )
    monkeypatch.setattr(
        "app.services.language_model_service.httpx.get",
        lambda *args, **kwargs: response,
    )
    client.post("/auth/register", json={"username": "first", "password": "password123"})
    assert client.post("/language-models/secondary/activate").status_code == 200
    assert client.post("/auth/logout").status_code == 204
    client.post("/auth/register", json={"username": "second", "password": "password123"})

    assert client.get("/language-models").json()["active_endpoint_key"] == "primary"
    db.expire_all()
    assert user_repository.get_user_by_username(db, "first").active_llm_endpoint_key == "secondary"
    assert user_repository.get_user_by_username(db, "second").active_llm_endpoint_key is None


def test_user_rejects_unavailable_language_model(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_endpoints(monkeypatch)
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "http://secondary:8010/v1/models"),
        json={"data": [{"id": "wrong-model"}]},
    )
    monkeypatch.setattr(
        "app.services.language_model_service.httpx.get",
        lambda *args, **kwargs: response,
    )
    client.post("/auth/register", json={"username": "student", "password": "password123"})

    result = client.post("/language-models/secondary/activate")

    assert result.status_code == 502
    assert result.json()["detail"] == "Selected endpoint does not serve the configured model"
