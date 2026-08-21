import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import user_repository
from app.services import language_model_service


pytestmark = pytest.mark.integration
ADMIN_PASSWORD = "Secure!Integration2026"
TEST_API_KEY = "integration-admin-key"


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


def _payload(
    *,
    model: str = "model-b",
    authentication: str = "managed",
    api_key: str | None = TEST_API_KEY,
) -> dict:
    """관리자 endpoint 생성·수정 요청 본문을 만든다."""
    payload = {
        "key": "secondary",
        "display_name": "Secondary model",
        "base_url": "http://secondary:8010/v1",
        "model": model,
        "supports_vision": True,
        "enabled": True,
        "authentication": authentication,
    }
    if api_key is not None:
        payload["api_key"] = api_key
    return payload


def _models_response(model: str = "model-b") -> httpx.Response:
    """연결 검증에 사용할 OpenAI 호환 models 응답을 만든다."""
    return httpx.Response(
        200,
        request=httpx.Request("GET", "http://secondary:8010/v1/models"),
        json={"data": [{"id": model}]},
    )


def _allow_secondary(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[dict] | None = None,
) -> None:
    """primary와 secondary endpoint 연결 검증을 성공 응답으로 고정한다."""
    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        if calls is not None:
            calls.append({"url": url, "headers": kwargs.get("headers")})
        return _models_response(
            "model-a" if "primary" in url else "model-b"
        )

    monkeypatch.setattr(language_model_service.httpx, "get", fake_get)


def _admin_state(client: TestClient) -> dict:
    """현재 관리자 endpoint 상태를 성공 응답으로 조회한다."""
    response = client.get("/admin/language-models")
    assert response.status_code == 200
    return _assert_write_only_response(response)

def _assert_write_only_response(response, *plaintexts: str) -> dict:
    """관리자 응답과 상태가 credential 평문·암호문을 공개하지 않는지 확인한다."""
    assert all(plaintext not in response.text for plaintext in plaintexts)
    payload = response.json()
    for endpoint in payload["endpoints"]:
        assert "api_key" not in endpoint
        assert "api_key_ciphertext" not in endpoint
        assert "api_key_env" not in endpoint
        assert endpoint["authentication"] in {"none", "managed"}
        assert isinstance(endpoint["api_key_configured"], bool)
    return payload


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
    primary = next(endpoint for endpoint in state["endpoints"] if endpoint["key"] == "primary")
    assert primary["authentication"] == "none"
    assert primary["api_key_configured"] is False
    assert client.post("/admin/language-models", json=_payload()).status_code == 428
    rejected_key = client.post(
        "/admin/language-models",
        json=_payload(authentication="none", api_key=TEST_API_KEY),
        headers={"If-Match": state["revision"]},
    )
    assert rejected_key.status_code == 422
    assert TEST_API_KEY not in rejected_key.text


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
    created_state = _assert_write_only_response(response, TEST_API_KEY)
    assert created_state["revision"] != revision
    created_endpoint = next(
        endpoint for endpoint in created_state["endpoints"] if endpoint["key"] == "secondary"
    )
    assert created_endpoint["authentication"] == "managed"
    assert created_endpoint["api_key_configured"] is True
    stored = json.loads(language_model_service.registry.endpoint_file.read_text(encoding="utf-8"))
    stored_endpoint = next(
        endpoint for endpoint in stored["endpoints"] if endpoint["key"] == "secondary"
    )
    assert stored_endpoint["authentication"] == "managed"
    assert isinstance(stored_endpoint["api_key_ciphertext"], str)
    assert stored_endpoint["api_key_ciphertext"]
    assert TEST_API_KEY not in json.dumps(stored)
    assert "api_key_env" not in stored_endpoint
    assert "secondary" in {
        endpoint["key"]
        for endpoint in client.get("/language-models").json()["endpoints"]
    }

def test_admin_credential_lifecycle_is_write_only_and_rotatable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """managed credential 편집·rotation과 인증 전환이 암호문·Authorization에 반영된다."""
    _login_admin(client)
    calls: list[dict] = []
    _allow_secondary(monkeypatch, calls)
    initial = _admin_state(client)

    created = client.post(
        "/admin/language-models",
        json=_payload(),
        headers={"If-Match": initial["revision"]},
    )
    assert created.status_code == 201
    created_state = _assert_write_only_response(created, TEST_API_KEY)
    created_endpoint = next(
        endpoint for endpoint in created_state["endpoints"] if endpoint["key"] == "secondary"
    )
    created_json = json.loads(language_model_service.registry.endpoint_file.read_text())
    created_stored = next(
        endpoint for endpoint in created_json["endpoints"] if endpoint["key"] == "secondary"
    )
    initial_ciphertext = created_stored["api_key_ciphertext"]
    initial_authorization = calls[-1]["headers"]["Authorization"]
    assert created_endpoint["api_key_configured"] is True

    calls.clear()
    preserved = client.put(
        "/admin/language-models/secondary",
        json=_payload(api_key=None),
        headers={"If-Match": created_state["revision"]},
    )
    assert preserved.status_code == 200
    preserved_state = _assert_write_only_response(preserved, TEST_API_KEY)
    preserved_json = json.loads(language_model_service.registry.endpoint_file.read_text())
    preserved_stored = next(
        endpoint for endpoint in preserved_json["endpoints"] if endpoint["key"] == "secondary"
    )
    assert preserved_stored["api_key_ciphertext"] == initial_ciphertext
    assert TEST_API_KEY not in json.dumps(preserved_json)
    assert calls[-1]["headers"]["Authorization"] == initial_authorization

    rotated_key = "integration-rotated-key"
    calls.clear()
    rotated = client.put(
        "/admin/language-models/secondary",
        json=_payload(api_key=rotated_key),
        headers={"If-Match": preserved_state["revision"]},
    )
    assert rotated.status_code == 200
    rotated_state = _assert_write_only_response(rotated, rotated_key, TEST_API_KEY)
    rotated_json = json.loads(language_model_service.registry.endpoint_file.read_text())
    rotated_stored = next(
        endpoint for endpoint in rotated_json["endpoints"] if endpoint["key"] == "secondary"
    )
    assert rotated_stored["api_key_ciphertext"] != initial_ciphertext
    rotated_serialized = json.dumps(rotated_json)
    assert TEST_API_KEY not in rotated_serialized
    assert rotated_key not in rotated_serialized
    assert calls[-1]["headers"]["Authorization"] != initial_authorization

    none = client.put(
        "/admin/language-models/secondary",
        json=_payload(authentication="none", api_key=None),
        headers={"If-Match": rotated_state["revision"]},
    )
    assert none.status_code == 200
    none_state = _assert_write_only_response(none, rotated_key, TEST_API_KEY)
    none_json = json.loads(language_model_service.registry.endpoint_file.read_text())
    none_raw = language_model_service.registry.endpoint_file.read_bytes()
    none_stored = next(
        endpoint for endpoint in none_json["endpoints"] if endpoint["key"] == "secondary"
    )
    assert none_stored["authentication"] == "none"
    none_serialized = json.dumps(none_json)
    assert rotated_key not in none_serialized
    assert TEST_API_KEY not in none_serialized
    assert "api_key_ciphertext" not in none_stored
    assert next(
        endpoint for endpoint in none_state["endpoints"] if endpoint["key"] == "secondary"
    )["api_key_configured"] is False

    missing_key = client.put(
        "/admin/language-models/secondary",
        json=_payload(authentication="managed", api_key=None),
        headers={"If-Match": none_state["revision"]},
    )
    assert missing_key.status_code == 422
    assert language_model_service.registry.endpoint_file.read_bytes() == none_raw

    restored_key = "integration-restored-key"
    restored = client.put(
        "/admin/language-models/secondary",
        json=_payload(api_key=restored_key),
        headers={"If-Match": none_state["revision"]},
    )
    assert restored.status_code == 200
    restored_state = _assert_write_only_response(restored, restored_key)
    restored_stored = next(
        endpoint
        for endpoint in json.loads(language_model_service.registry.endpoint_file.read_text())[
            "endpoints"
        ]
        if endpoint["key"] == "secondary"
    )
    assert restored_stored["authentication"] == "managed"
    restored_serialized = json.dumps(
        json.loads(language_model_service.registry.endpoint_file.read_text())
    )
    assert restored_key not in restored_serialized
    assert isinstance(restored_stored["api_key_ciphertext"], str)
    assert next(
        endpoint for endpoint in restored_state["endpoints"] if endpoint["key"] == "secondary"
    )["api_key_configured"] is True


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
    created_response = client.post(
        "/admin/language-models",
        json=_payload(),
        headers={"If-Match": state["revision"]},
    )
    assert created_response.status_code == 201
    created = _assert_write_only_response(created_response, TEST_API_KEY)

    changed = client.post(
        "/admin/language-models/secondary/default",
        headers={"If-Match": created["revision"]},
    )
    assert changed.status_code == 200
    changed_state = _assert_write_only_response(changed, TEST_API_KEY)
    assert changed_state["default_endpoint_key"] == "secondary"
    assert client.delete(
        "/admin/language-models/secondary",
        headers={"If-Match": changed_state["revision"]},
    ).status_code == 409

    restored_response = client.post(
        "/admin/language-models/primary/default",
        headers={"If-Match": changed_state["revision"]},
    )
    assert restored_response.status_code == 200
    restored = _assert_write_only_response(restored_response, TEST_API_KEY)
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
    _assert_write_only_response(deleted, TEST_API_KEY)
    assert client.post("/auth/logout").status_code == 204
    assert client.post(
        "/auth/login",
        json={"username": "student", "password": "password123"},
    ).status_code == 200
    assert client.get("/language-models").json()["active_endpoint_key"] == "primary"
    db.expire_all()
    assert user_repository.get_user_by_username(db, "student").active_llm_endpoint_key == "secondary"
