import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app


pytestmark = pytest.mark.integration


def test_registration_login_logout_and_bootstrap_admin(client: TestClient) -> None:
    admin_login = client.post("/auth/login", json={"username": "admin", "password": "admin"})
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

