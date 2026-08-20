import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatSession
from app.models.retrieval_config import ReindexJob
from app.repositories import retrieval_config_repository


pytestmark = pytest.mark.integration


def _login_admin(client: TestClient) -> None:
    """관리자 검색 API 검증에 필요한 강제 비밀번호 변경을 마친다."""
    bootstrap_password = "Test!Bootstrap2026"
    response = client.post(
        "/auth/login",
        json={"username": "admin", "password": bootstrap_password},
    )
    assert response.status_code == 200
    changed = client.post(
        "/auth/password",
        json={
            "current_password": bootstrap_password,
            "new_password": "Secure!Integration2026",
        },
    )
    assert changed.status_code == 200


def test_admin_state_and_role_boundary(client: TestClient) -> None:
    """검색 관리 상태가 인증과 관리자 역할로 보호되는지 검증한다."""
    assert client.get("/admin/retrieval").status_code == 401

    assert client.post(
        "/auth/register",
        json={"username": "student", "password": "password123"},
    ).status_code == 201
    assert client.get("/admin/retrieval").status_code == 403

    assert client.post("/auth/logout").status_code == 204
    _login_admin(client)
    state = client.get("/admin/retrieval")

    assert state.status_code == 200
    assert len(state.json()["presets"]) == 5
    assert len(state.json()["search_algorithms"]) == 4
    assert state.json()["active_preset_key"] == "balanced"
    assert state.json()["active_search_algorithm_key"] == "dense"


def test_algorithm_change_is_immediate_and_does_not_reindex(
    client: TestClient,
    db: Session,
) -> None:
    """검색 알고리즘 변경이 재색인 없이 즉시 반영되는지 검증한다."""
    _login_admin(client)

    response = client.post("/admin/retrieval/algorithms/hybrid/activate")

    assert response.status_code == 200
    assert response.json()["key"] == "hybrid"
    db.expire_all()
    configuration = retrieval_config_repository.get_configuration(db)
    assert configuration.active_search_algorithm_key == "hybrid"
    assert configuration.index_version == 1
    assert db.scalar(select(func.count()).select_from(ReindexJob)) == 0


def test_chunking_preset_change_completes_reindex_job(client: TestClient, db: Session) -> None:
    """청킹 프리셋 변경이 재색인 작업 완료까지 이어지는지 검증한다."""
    _login_admin(client)

    response = client.post("/admin/retrieval/presets/standard/activate")

    assert response.status_code == 202
    state = client.get("/admin/retrieval").json()
    assert state["active_preset_key"] == "standard"
    assert state["index_version"] == 2
    assert state["maintenance_mode"] is False
    assert state["latest_job"]["status"] == "completed"


def test_unknown_algorithm_is_rejected(client: TestClient) -> None:
    """등록되지 않은 검색 알고리즘 활성화를 거부하는지 검증한다."""
    _login_admin(client)

    assert client.post("/admin/retrieval/algorithms/not-real/activate").status_code == 404


def test_admin_can_list_stored_retrieval_traces(
    client: TestClient,
    db: Session,
    user_factory,
) -> None:
    """관리자만 저장된 검색 추적 기록을 조회할 수 있는지 검증한다."""
    owner = user_factory("trace-owner")
    session = ChatSession(owner_id=owner.id, title="trace session")
    db.add(session)
    db.flush()
    message = ChatMessage(
        session_id=session.id,
        role="assistant",
        content="답변",
        message_metadata={
            "sources": [],
            "retrieval_trace": {
                "schema_version": 1,
                "request_id": "trace-request",
                "query_plan": {"queries": ["질문"]},
                "retrieval_events": [],
                "coverage_events": [],
                "outcome": {"status": "no_source"},
            },
        },
    )
    db.add(message)
    db.commit()

    assert client.get("/admin/retrieval/traces").status_code == 401
    _login_admin(client)
    response = client.get("/admin/retrieval/traces?limit=10")

    assert response.status_code == 200
    assert response.json()["traces"][0]["message_id"] == message.id
    assert response.json()["traces"][0]["username"] == "trace-owner"
    assert response.json()["traces"][0]["trace"]["request_id"] == "trace-request"
