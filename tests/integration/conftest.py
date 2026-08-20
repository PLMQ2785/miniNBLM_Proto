from collections.abc import Callable, Generator
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, engine
from app.main import app
from app.models.document import Document
from app.models.user import User
from app.services.auth_service import password_hash


# Never let a misconfigured test command truncate a developer database.
def _assert_isolated_test_database() -> None:
    if (
        os.environ.get("MININBLM_TEST_DATABASE") != "1"
        or engine.url.database != "rag_test_db"
        or engine.url.port != 55432
    ):
        raise RuntimeError(
            "Integration tests require the isolated test database. "
            "Run ./scripts/test.sh instead."
        )


def _reset_mutable_data() -> None:
    _assert_isolated_test_database()
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE auth_sessions, chat_messages, chat_sessions, chunks, "
                "document_pages, reindex_jobs, documents, users RESTART IDENTITY CASCADE"
            )
        )
        # Built-in retrieval rows persist across tests, so reset their mutable singleton.
        connection.execute(
            text(
                "UPDATE retrieval_configuration SET "
                "active_preset_key='balanced', pending_preset_key=NULL, "
                "active_search_algorithm_key='dense', index_version=1, "
                "maintenance_mode=false, updated_at=now() WHERE id=1"
            )
        )


@pytest.fixture(autouse=True)
def reset_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    _reset_mutable_data()
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    yield
    _reset_mutable_data()


@pytest.fixture
def client(reset_database) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db(reset_database) -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def user_factory(db: Session) -> Callable[..., User]:
    def create_user(username: str, *, role: str = "user", password: str = "password123") -> User:
        user = User(
            username=username,
            password_hash=password_hash.hash(password),
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return create_user


@pytest.fixture
def document_factory(db: Session, tmp_path: Path) -> Callable[..., Document]:
    def create_document(
        owner: User,
        *,
        title: str = "lesson.pdf",
        status: str = "indexed",
        file_exists: bool = True,
    ) -> Document:
        file_path = tmp_path / f"{owner.username}-{title}"
        if file_exists:
            file_path.write_bytes(b"%PDF-1.4\n% test\n")
        document = Document(
            owner_id=owner.id,
            title=title,
            file_path=str(file_path),
            mime_type="application/pdf",
            status=status,
            indexed_preset_key="balanced" if status == "indexed" else None,
            index_version=1 if status == "indexed" else None,
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        return document

    return create_document
