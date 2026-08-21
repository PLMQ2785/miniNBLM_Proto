import json
import os
from collections.abc import Callable, Generator
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
from app.services import language_model_service
from app.services.auth_service import password_hash
from app.services.language_model_registry import LanguageModelRegistry


# 개발자 DB를 잘못 비우지 않도록 격리 설정을 먼저 확인한다.
def _assert_isolated_test_database() -> None:
    """통합 테스트가 전용 DB에만 접근하는지 확인한다."""
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
    """테스트 간 가변 DB 상태를 초기값으로 되돌린다."""
    _assert_isolated_test_database()
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE auth_sessions, chat_messages, chat_sessions, chunks, "
                "document_pages, reindex_jobs, documents, users RESTART IDENTITY CASCADE"
            )
        )
        # 공용 검색 설정 행은 유지하되 변경 가능한 값만 초기화한다.
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
    """각 테스트 전후 DB와 업로드 경로를 격리한다."""
    _reset_mutable_data()
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    endpoint_file = tmp_path / "llm-endpoints.json"
    master_key_file = tmp_path / "master.key"
    endpoint_file.write_text(
        json.dumps(
            {
                "default_endpoint": "primary",
                "endpoints": [
                    {
                        "key": "primary",
                        "display_name": "Primary model",
                        "base_url": "http://primary:8010/v1",
                        "authentication": "none",
                        "model": "model-a",
                        "supports_vision": True,
                        "enabled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        language_model_service,
        "registry",
        LanguageModelRegistry(endpoint_file, master_key_file),
    )
    yield
    _reset_mutable_data()


@pytest.fixture
def client(reset_database) -> Generator[TestClient, None, None]:
    """실제 앱 수명주기를 거치는 API 클라이언트를 제공한다."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db(reset_database) -> Generator[Session, None, None]:
    """테스트별 트랜잭션을 정리하는 DB 세션을 제공한다."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def user_factory(db: Session) -> Callable[..., User]:
    """DB에 커밋된 사용자 생성 함수를 제공한다."""
    def create_user(username: str, *, role: str = "user", password: str = "password123") -> User:
        """격리 계약 검증에 사용할 사용자를 생성한다."""
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
    """소유자별 문서와 선택적 원본 파일을 생성한다."""
    def create_document(
        owner: User,
        *,
        title: str = "lesson.pdf",
        status: str = "indexed",
        file_exists: bool = True,
    ) -> Document:
        """검색·복구 테스트용 문서 레코드와 파일을 생성한다."""
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
