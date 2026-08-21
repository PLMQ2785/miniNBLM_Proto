import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import user_repository
from app.services import language_model_service


pytestmark = pytest.mark.integration
ADMIN_PASSWORD = "Secure!Integration2026"


def _login_admin(client: TestClient) -> None:
    """관리자 endpoint API 검증에 필요한 강제 비밀번호 변경을 마친다."""
    bootstrap_password = "Test!Bootstrap2026"
    response = client.post(
        "/auth/login",
        json={"username": "admin", "password": bootstrap_password},
    )
    assert response.status_code == 200
    changed = client.post(
        "/auth/password",
        json={"current_password": bootstrap_password, "new_password": ADMIN_PASSWORD},
    )
    assert changed.status_code == 200


def _relogin_admin(client: TestClient) -> None:
    """비밀번호 변경을 마친 bootstrap 관리자로 다시 로그인한다."""
    response = client.post(
        "/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200


def _payload(*, model: str = "model-b") -> dict:
    """관리자 endpoint 생성·수정 요청 본문을 만든다."""
    return {
        "key": "secondary",
        "display_name": "Secondary model",
        "base_url": "http://secondary:8010/v1",
        "api_key_env": "TEST_LLM_API_KEY",
        "model": model,
        "supports_vision": True,
        "enabled": True,
    }


def _models_response(model: str = "model-b") -> httpx.Response:
    """연결 검증에 사용할 OpenAI 호환 models 응답을 만든다."""
    return httpx.Response(
        200,
        request=httpx.Request("GET", "http://secondary:8010/v1/models"),
        json={"data": [{"id": model}]},
    )


def _allow_secondary(monkeypatch: pytest.MonkeyPatch) -> None:
    """primary와 secondary endpoint 연결 검증을 성공 응답으로 고정한다."""
    monkeypatch.setattr(
        language_model_service.httpx,
        "get",
        lambda url, **kwargs: _models_response(
            "model-a" if "primary" in url else "model-b"
        ),
    )


def _admin_state(client: TestClient) -> dict:
    """현재 관리자 endpoint 상태를 성공 응답으로 조회한다."""
    response = client.get("/admin/language-models")
    assert response.status_code == 200
    return response.json()


def test_language_model_admin_api_enforces_role_and_revision(client: TestClient) -> None:
    """JSON 전체 상태와 수정은 관리자·revision 경계로 보호된다."""
    assert client.get("/admin/language-models").status_code == 401
    assert client.post(
        "/auth/register",
        json={"username": "student", "password": "password123"},
    ).status_code == 201
    assert client.get("/admin/language-models").status_code == 403

    assert client.post("/auth/logout").status_code == 204
    _login_admin(client)
    state = _admin_state(client)

    assert state["default_endpoint_key"] == "primary"
    assert len(state["revision"]) == 64
    assert client.post("/admin/language-models", json=_payload()).status_code == 428


def test_admin_create_persists_reference_and_updates_user_list_immediately(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """검증된 endpoint가 credential 값 없이 JSON과 사용자 목록에 즉시 반영된다."""
    _login_admin(client)
    _allow_secondary(monkeypatch)
    revision = _admin_state(client)["revision"]

    response = client.post(
        "/admin/language-models",
        json=_payload(),
        headers={"If-Match": revision},
    )

    assert response.status_code == 201
    assert response.json()["revision"] != revision
    assert "integration-secret" not in response.text
    stored = json.loads(language_model_service.registry.endpoint_file.read_text(encoding="utf-8"))
    assert stored["endpoints"][1]["api_key_env"] == "TEST_LLM_API_KEY"
    assert "api_key" not in stored["endpoints"][1]
    assert "secondary" in {
        endpoint["key"]
        for endpoint in client.get("/language-models").json()["endpoints"]
    }


def test_failed_connection_and_stale_revision_leave_json_unchanged(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """연결 실패와 동시 수정 충돌은 마지막 정상 JSON을 보존한다."""
    _login_admin(client)
    state = _admin_state(client)
    original = language_model_service.registry.endpoint_file.read_bytes()
    monkeypatch.setattr(
        language_model_service.httpx,
        "get",
        lambda *args, **kwargs: _models_response("wrong-model"),
    )

    unavailable = client.post(
        "/admin/language-models",
        json=_payload(),
        headers={"If-Match": state["revision"]},
    )

    assert unavailable.status_code == 502
    assert language_model_service.registry.endpoint_file.read_bytes() == original

    _allow_secondary(monkeypatch)
    created = client.post(
        "/admin/language-models",
        json=_payload(),
        headers={"If-Match": state["revision"]},
    )
    assert created.status_code == 201
    stale = client.put(
        "/admin/language-models/secondary",
        json={**_payload(), "display_name": "Stale edit"},
        headers={"If-Match": state["revision"]},
    )
    assert stale.status_code == 409
    assert _admin_state(client)["endpoints"][1]["display_name"] == "Secondary model"


def test_default_change_and_deleted_user_selection_fall_back_on_next_request(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """기본값과 삭제 fallback은 재시작 없이 다음 사용자 요청부터 적용된다."""
    _login_admin(client)
    _allow_secondary(monkeypatch)
    state = _admin_state(client)
    created = client.post(
        "/admin/language-models",
        json=_payload(),
        headers={"If-Match": state["revision"]},
    ).json()

    changed = client.post(
        "/admin/language-models/secondary/default",
        headers={"If-Match": created["revision"]},
    )
    assert changed.status_code == 200
    assert changed.json()["default_endpoint_key"] == "secondary"
    assert client.delete(
        "/admin/language-models/secondary",
        headers={"If-Match": changed.json()["revision"]},
    ).status_code == 409

    restored = client.post(
        "/admin/language-models/primary/default",
        headers={"If-Match": changed.json()["revision"]},
    ).json()
    assert client.post("/auth/logout").status_code == 204
    assert client.post(
        "/auth/register",
        json={"username": "student", "password": "password123"},
    ).status_code == 201
    assert client.post("/language-models/secondary/activate").status_code == 200
    assert client.post("/auth/logout").status_code == 204
    _relogin_admin(client)

    deleted = client.delete(
        "/admin/language-models/secondary",
        headers={"If-Match": restored["revision"]},
    )

    assert deleted.status_code == 200
    assert client.post("/auth/logout").status_code == 204
    assert client.post(
        "/auth/login",
        json={"username": "student", "password": "password123"},
    ).status_code == 200
    assert client.get("/language-models").json()["active_endpoint_key"] == "primary"
    db.expire_all()
    assert user_repository.get_user_by_username(db, "student").active_llm_endpoint_key == "secondary"
