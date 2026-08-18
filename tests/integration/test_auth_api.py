from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.main import app
from app.models.chat import ChatMessage, ChatSession
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.page import DocumentPage
from app.models.retrieval_config import ReindexJob
from app.models.user import AuthSession, User


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


def test_regular_user_can_change_password_and_other_sessions_are_revoked(
    reset_database,
) -> None:
    new_password = "Changed!Secure2026"
    with TestClient(app) as client, TestClient(app) as other_session:
        assert client.post(
            "/auth/register",
            json={"username": "member", "password": "password123"},
        ).status_code == 201
        assert other_session.post(
            "/auth/login",
            json={"username": "member", "password": "password123"},
        ).status_code == 200

        changed = client.post(
            "/auth/password",
            json={
                "current_password": "password123",
                "new_password": new_password,
            },
        )

        assert changed.status_code == 200
        assert other_session.get("/auth/me").status_code == 401
        assert client.post("/auth/logout").status_code == 204
        assert client.post(
            "/auth/login",
            json={"username": "member", "password": "password123"},
        ).status_code == 401
        assert client.post(
            "/auth/login",
            json={"username": "member", "password": new_password},
        ).status_code == 200


def test_account_deletion_removes_owned_data_files_and_sessions(
    reset_database,
    db: Session,
    document_factory,
) -> None:
    with TestClient(app) as client, TestClient(app) as other_session:
        registration = client.post(
            "/auth/register",
            json={"username": "departing", "password": "password123"},
        )
        assert registration.status_code == 201
        assert other_session.post(
            "/auth/login",
            json={"username": "departing", "password": "password123"},
        ).status_code == 200

        from app.repositories import user_repository

        user = user_repository.get_user_by_username(db, "departing")
        document = document_factory(user, title="private.pdf")
        document_dir = Path(settings.upload_dir) / "documents" / str(document.id)
        document_dir.mkdir(parents=True)
        original_file = document_dir / "original-test.pdf"
        original_file.write_bytes(b"%PDF-1.4\n% account deletion test\n")
        document.file_path = str(original_file)

        page = DocumentPage(document_id=document.id, page_number=1, text="private page")
        chunk = Chunk(
            document_id=document.id,
            page_start=1,
            page_end=1,
            chunk_index=0,
            content="private chunk",
            embedding=None,
        )
        chat_session = ChatSession(owner_id=user.id, title="private chat")
        db.add_all([page, chunk, chat_session])
        db.flush()
        db.add(ChatMessage(session_id=chat_session.id, role="user", content="private question"))
        job = ReindexJob(
            requested_by=user.id,
            source_preset_key="balanced",
            target_preset_key="balanced",
            target_index_version=2,
            status="completed",
            reindex_documents=False,
            rebuild_vector_index=False,
            runtime_settings_changed=False,
        )
        db.add(job)
        db.commit()
        user_id = user.id
        document_id = document.id
        job_id = job.id

        wrong_password = client.request(
            "DELETE",
            "/auth/account",
            json={
                "current_password": "incorrect-password",
                "username_confirmation": "departing",
            },
        )
        assert wrong_password.status_code == 400
        wrong_confirmation = client.request(
            "DELETE",
            "/auth/account",
            json={
                "current_password": "password123",
                "username_confirmation": "someone-else",
            },
        )
        assert wrong_confirmation.status_code == 400

        deleted = client.request(
            "DELETE",
            "/auth/account",
            json={
                "current_password": "password123",
                "username_confirmation": "departing",
            },
        )

        assert deleted.status_code == 204
        assert deleted.content == b""
        assert client.get("/auth/me").status_code == 401
        assert other_session.get("/auth/me").status_code == 401
        db.expire_all()
        assert db.scalar(select(func.count()).select_from(User).where(User.id == user_id)) == 0
        assert db.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.user_id == user_id)) == 0
        assert db.scalar(select(func.count()).select_from(Document).where(Document.id == document_id)) == 0
        assert db.scalar(select(func.count()).select_from(DocumentPage).where(DocumentPage.document_id == document_id)) == 0
        assert db.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)) == 0
        assert db.scalar(select(func.count()).select_from(ChatSession).where(ChatSession.owner_id == user_id)) == 0
        assert db.get(ReindexJob, job_id).requested_by is None
        assert not document_dir.exists()
        assert client.post(
            "/auth/login",
            json={"username": "departing", "password": "password123"},
        ).status_code == 401


def test_account_deletion_is_blocked_while_a_document_is_processing(
    client: TestClient,
    db: Session,
    document_factory,
) -> None:
    assert client.post(
        "/auth/register",
        json={"username": "busy-member", "password": "password123"},
    ).status_code == 201

    from app.repositories import user_repository

    user = user_repository.get_user_by_username(db, "busy-member")
    document = document_factory(user, status="processing")

    response = client.request(
        "DELETE",
        "/auth/account",
        json={
            "current_password": "password123",
            "username_confirmation": "busy-member",
        },
    )

    assert response.status_code == 409
    assert client.get("/auth/me").status_code == 200
    assert db.get(Document, document.id) is not None


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


def test_admin_password_reset_revokes_sessions_and_forces_password_change(
    reset_database,
) -> None:
    temporary_password = "Temporary!Reset2026"
    final_password = "Final!Member2026"
    with (
        TestClient(app) as admin,
        TestClient(app) as member,
        TestClient(app) as other_member_session,
    ):
        assert member.post(
            "/auth/register",
            json={"username": "reset-member", "password": "password123"},
        ).status_code == 201
        assert other_member_session.post(
            "/auth/login",
            json={"username": "reset-member", "password": "password123"},
        ).status_code == 200

        forbidden = member.post(
            "/admin/users/password-reset",
            json={"username": "reset-member", "temporary_password": temporary_password},
        )
        assert forbidden.status_code == 403

        assert admin.post(
            "/auth/login",
            json={"username": "admin", "password": BOOTSTRAP_PASSWORD},
        ).status_code == 200
        assert admin.post(
            "/auth/password",
            json={
                "current_password": BOOTSTRAP_PASSWORD,
                "new_password": NEW_ADMIN_PASSWORD,
            },
        ).status_code == 200

        reset = admin.post(
            "/admin/users/password-reset",
            json={"username": "reset-member", "temporary_password": temporary_password},
        )
        assert reset.status_code == 200
        assert reset.json()["username"] == "reset-member"
        assert reset.json()["must_change_password"] is True
        assert member.get("/auth/me").status_code == 401
        assert other_member_session.get("/auth/me").status_code == 401

        assert member.post(
            "/auth/login",
            json={"username": "reset-member", "password": "password123"},
        ).status_code == 401
        temporary_login = member.post(
            "/auth/login",
            json={"username": "reset-member", "password": temporary_password},
        )
        assert temporary_login.status_code == 200
        assert temporary_login.json()["user"]["must_change_password"] is True
        assert member.get("/documents").status_code == 403
        assert member.post(
            "/auth/password",
            json={
                "current_password": temporary_password,
                "new_password": final_password,
            },
        ).status_code == 200

        self_reset = admin.post(
            "/admin/users/password-reset",
            json={"username": "admin", "temporary_password": "Other!Admin2026"},
        )
        assert self_reset.status_code == 409
