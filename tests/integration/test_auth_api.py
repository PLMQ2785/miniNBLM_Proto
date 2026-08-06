import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app


pytestmark = pytest.mark.integration

BOOTSTRAP_PASSWORD = "Test!Bootstrap2026"
NEW_ADMIN_PASSWORD = "General!Secure2026"


def test_bootstrap_admin_must_change_password_and_old_secret_is_not_restored(
    reset_database,
) -> None:
    with TestClient(app) as client, TestClient(app) as other_session:
        admin_login = client.post(
            "/auth/login",
            json={"username": "admin", "password": BOOTSTRAP_PASSWORD},
        )
        assert admin_login.status_code == 200
        assert admin_login.json()["user"] == {
            "user_id": admin_login.json()["user"]["user_id"],
            "username": "admin",
            "role": "admin",
            "must_change_password": True,
        }
        blocked = client.get("/documents")
        assert blocked.status_code == 403
        assert blocked.json()["detail"] == "Password change required"

        assert other_session.post(
            "/auth/login",
            json={"username": "admin", "password": BOOTSTRAP_PASSWORD},
        ).status_code == 200

        wrong_current = client.post(
            "/auth/password",
            json={
                "current_password": "incorrect-password",
                "new_password": NEW_ADMIN_PASSWORD,
            },
        )
        assert wrong_current.status_code == 400

        weak_password = client.post(
            "/auth/password",
            json={
                "current_password": BOOTSTRAP_PASSWORD,
                "new_password": "lowercaseonly",
            },
        )
        assert weak_password.status_code == 400

        reused_password = client.post(
            "/auth/password",
            json={
                "current_password": BOOTSTRAP_PASSWORD,
                "new_password": BOOTSTRAP_PASSWORD,
            },
        )
        assert reused_password.status_code == 409

        changed = client.post(
            "/auth/password",
            json={
                "current_password": BOOTSTRAP_PASSWORD,
                "new_password": NEW_ADMIN_PASSWORD,
            },
        )
        assert changed.status_code == 200
        assert changed.json()["user"]["must_change_password"] is False
        assert client.get("/documents").status_code == 200
        assert other_session.get("/auth/me").status_code == 401

        assert client.post("/auth/logout").status_code == 204
        assert client.post(
            "/auth/login",
            json={"username": "admin", "password": BOOTSTRAP_PASSWORD},
        ).status_code == 401
        assert client.post(
            "/auth/login",
            json={"username": "admin", "password": NEW_ADMIN_PASSWORD},
        ).status_code == 200

    # A later application startup must not restore the environment bootstrap secret.
    with TestClient(app) as restarted_client:
        assert restarted_client.post(
            "/auth/login",
            json={"username": "admin", "password": BOOTSTRAP_PASSWORD},
        ).status_code == 401
        restarted_login = restarted_client.post(
            "/auth/login",
            json={"username": "admin", "password": NEW_ADMIN_PASSWORD},
        )
        assert restarted_login.status_code == 200
        assert restarted_login.json()["user"]["must_change_password"] is False


def test_registration_login_and_logout(client: TestClient) -> None:
    admin_login = client.post(
        "/auth/login",
        json={"username": "admin", "password": BOOTSTRAP_PASSWORD},
    )
    assert admin_login.status_code == 200
    assert admin_login.json()["user"]["role"] == "admin"

    assert client.post("/auth/logout").status_code == 204
    assert client.post(
        "/auth/register",
        json={"username": "student", "password": "short"},
    ).status_code == 422

    registration = client.post(
        "/auth/register",
        json={"username": "student", "password": "password123"},
    )
    assert registration.status_code == 201
    assert registration.json()["user"]["username"] == "student"
    assert registration.json()["user"]["must_change_password"] is False
    assert client.get("/auth/me").status_code == 200
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/documents").status_code == 401


def test_documents_are_isolated_by_user(reset_database, db: Session, document_factory) -> None:
    with TestClient(app) as first, TestClient(app) as second:
        assert first.post(
            "/auth/register",
            json={"username": "first", "password": "password123"},
        ).status_code == 201
        assert second.post(
            "/auth/register",
            json={"username": "second", "password": "password123"},
        ).status_code == 201

        from app.repositories import user_repository

        first_user = user_repository.get_user_by_username(db, "first")
        second_user = user_repository.get_user_by_username(db, "second")
        first_document = document_factory(first_user, title="first.pdf")
        second_document = document_factory(second_user, title="second.pdf")

        assert [row["document_id"] for row in first.get("/documents").json()["documents"]] == [
            first_document.id
        ]
        assert [row["document_id"] for row in second.get("/documents").json()["documents"]] == [
            second_document.id
        ]
        assert first.get(f"/documents/{second_document.id}").status_code == 404
        assert second.delete(f"/documents/{first_document.id}").status_code == 404
