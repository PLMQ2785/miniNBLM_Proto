import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import chat as chat_api
from app.models.chat import ChatMessage, ChatSession
from app.repositories import user_repository
from app.schemas.chat import SourceRef
from app.services.generator import GeneratedAnswer
from app.services.retriever import RetrievedChunk


pytestmark = pytest.mark.integration


def test_chat_persists_messages_and_returns_sources(
    client: TestClient,
    db: Session,
    document_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert client.post(
        "/auth/register",
        json={"username": "student", "password": "password123"},
    ).status_code == 201
    user = user_repository.get_user_by_username(db, "student")
    document = document_factory(user)
    retrieved = RetrievedChunk(
        chunk_id=101,
        document_id=document.id,
        content="낙상 발생 시 환자를 바로 일으키지 않고 손상 여부를 확인한다.",
        page_start=4,
        page_end=4,
        score=0.9,
        source_refs={"page": 4},
    )
    monkeypatch.setattr(chat_api, "retrieve_chunks", lambda **kwargs: [retrieved])
    monkeypatch.setattr(
        chat_api,
        "generate_answer",
        lambda **kwargs: GeneratedAnswer(
            answer="손상 여부를 먼저 확인합니다.",
            sources=[SourceRef(document_id=document.id, page=4, chunk_id=101)],
        ),
    )

    response = client.post(
        "/chat",
        json={"document_id": document.id, "question": "낙상 후 무엇을 먼저 하나요?"},
    )

    assert response.status_code == 200
    assert response.json()["sources"] == [
        {"document_id": document.id, "page": 4, "chunk_id": 101}
    ]
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ChatSession)) == 1
    assert db.scalar(select(func.count()).select_from(ChatMessage)) == 2


def test_chat_rejects_another_users_document(
    client: TestClient,
    user_factory,
    document_factory,
) -> None:
    owner = user_factory("owner")
    document = document_factory(owner)
    assert client.post(
        "/auth/register",
        json={"username": "other", "password": "password123"},
    ).status_code == 201

    response = client.post(
        "/chat",
        json={"document_id": document.id, "question": "질문"},
    )

    assert response.status_code == 404
