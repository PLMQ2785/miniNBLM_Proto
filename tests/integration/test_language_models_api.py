import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import user_repository
from app.services import language_model_service
from app.services.language_model_service import LanguageModelEndpointDraft


pytestmark = pytest.mark.integration


def _models_response(model: str = "model-b") -> httpx.Response:
    """연결 검증에 사용할 OpenAI 호환 models 응답을 만든다."""
    return httpx.Response(
        200,
        request=httpx.Request("GET", "http://secondary:8010/v1/models"),
        json={"data": [{"id": model}]},
    )


def _add_secondary(monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON registry에 사용자 선택 검증용 두 번째 endpoint를 추가한다."""
    monkeypatch.setattr(
        language_model_service.httpx,
        "get",
        lambda *args, **kwargs: _models_response(),
    )
    snapshot = language_model_service.get_snapshot()
    language_model_service.create_endpoint(
        actor_id=1,
        expected_revision=snapshot.revision,
        draft=LanguageModelEndpointDraft(
            key="secondary",
            display_name="Secondary model",
            base_url="http://secondary:8010/v1",
            model="model-b",
            supports_vision=True,
            enabled=True,
            authentication="none",
        ),
    )


def test_language_models_require_login_and_are_available_to_regular_users(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """최신 JSON 모델 목록은 로그인을 요구하고 일반 사용자에게 제공된다."""
    _add_secondary(monkeypatch)
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
    """가용한 모델 선택이 응답과 사용자 DB 설정에 반영되는지 검증한다."""
    _add_secondary(monkeypatch)
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
    """활성 언어모델 선택이 사용자 사이에 격리되는지 검증한다."""
    _add_secondary(monkeypatch)
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
    """선택 model을 제공하지 않는 endpoint 활성화를 거부하는지 검증한다."""
    _add_secondary(monkeypatch)
    monkeypatch.setattr(
        language_model_service.httpx,
        "get",
        lambda *args, **kwargs: _models_response("wrong-model"),
    )
    client.post("/auth/register", json={"username": "student", "password": "password123"})

    result = client.post("/language-models/secondary/activate")

    assert result.status_code == 502
    assert result.json()["detail"] == "Selected endpoint does not serve the configured model"
