from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import documents as documents_api
from app.config import settings
from app.models.document import Document


pytestmark = pytest.mark.integration


def _pdf_bytes(*, password: str | None = None) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Valid test PDF")
    options = {}
    if password is not None:
        options = {
            "encryption": fitz.PDF_ENCRYPT_AES_256,
            "owner_pw": "owner-password",
            "user_pw": password,
        }
    payload = document.tobytes(**options)
    document.close()
    return payload


def _register(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={"username": "uploader", "password": "password123"},
    )
    assert response.status_code == 201


def test_upload_processing_conflict_and_delete(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register(client)
    monkeypatch.setattr(documents_api.document_processor, "process_document", lambda document_id: True)

    upload = client.post(
        "/documents",
        files={"file": ("lesson.pdf", _pdf_bytes(), "application/pdf")},
    )
    assert upload.status_code == 201
    document_id = upload.json()["document_id"]

    document = db.get(Document, document_id)
    assert document.status == "uploaded"
    stored_file = Path(document.file_path)
    assert stored_file.is_file()
    assert client.delete(f"/documents/{document_id}").status_code == 409

    document.status = "indexed"
    document.indexed_preset_key = "balanced"
    document.index_version = 1
    db.commit()

    assert client.delete(f"/documents/{document_id}").status_code == 204
    db.expire_all()
    assert db.get(Document, document_id) is None
    assert not stored_file.exists()


def test_non_pdf_upload_is_rejected(client: TestClient) -> None:
    _register(client)

    response = client.post(
        "/documents",
        files={"file": ("notes.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 400


def test_pdf_filename_extension_is_required(client: TestClient) -> None:
    _register(client)

    response = client.post(
        "/documents",
        files={"file": ("notes.txt", _pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "PDF filename must end with .pdf"


@pytest.mark.parametrize(
    ("payload", "expected_detail"),
    [
        (b"not a pdf", "valid PDF signature"),
        (b"%PDF-1.7\ncorrupt", "not a readable PDF"),
        (_pdf_bytes(password="secret"), "Password-protected PDFs"),
    ],
)
def test_invalid_pdf_upload_is_rejected_without_leaving_data(
    client: TestClient,
    db: Session,
    payload: bytes,
    expected_detail: str,
) -> None:
    _register(client)

    response = client.post(
        "/documents",
        files={"file": ("invalid.pdf", payload, "application/pdf")},
    )

    assert response.status_code == 400
    assert expected_detail in response.json()["detail"]
    assert db.scalar(select(func.count()).select_from(Document)) == 0
    assert not list(Path(settings.upload_dir).rglob("*.pdf"))


def test_oversized_pdf_is_rejected_without_leaving_data(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register(client)
    monkeypatch.setattr(settings, "max_upload_bytes", 100)

    response = client.post(
        "/documents",
        files={"file": ("large.pdf", _pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 413
    assert "100 byte upload limit" in response.json()["detail"]
    assert db.scalar(select(func.count()).select_from(Document)) == 0
    assert not list(Path(settings.upload_dir).rglob("*.pdf"))


def test_maintenance_blocks_document_upload(client: TestClient, db: Session) -> None:
    _register(client)
    from app.repositories import retrieval_config_repository

    configuration = retrieval_config_repository.get_configuration(db)
    configuration.maintenance_mode = True
    db.commit()

    response = client.post(
        "/documents",
        files={"file": ("lesson.pdf", b"%PDF-1.4\n", "application/pdf")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Retrieval maintenance is in progress"
