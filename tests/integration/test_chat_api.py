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
    retrieval_call = {}

    def retrieve_for_workspace(**kwargs):
        retrieval_call.update(kwargs)
        return [retrieved]

    monkeypatch.setattr(chat_api, "retrieve_chunks", retrieve_for_workspace)
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
        json={"question": "낙상 후 무엇을 먼저 하나요?"},
    )

    assert response.status_code == 200
    assert response.json()["sources"] == [
        {"document_id": document.id, "page": 4, "chunk_id": 101}
    ]
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ChatSession)) == 1
    assert db.scalar(select(func.count()).select_from(ChatMessage)) == 2
    session = db.scalar(select(ChatSession))
    assert session.owner_id == user.id
    assert session.document_id is None
    assert retrieval_call["owner_id"] == user.id
    assert "document_id" not in retrieval_call


def test_chat_returns_a_grounded_empty_result_without_document_selection(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert client.post(
        "/auth/register",
        json={"username": "empty-workspace", "password": "password123"},
    ).status_code == 201
    monkeypatch.setattr(chat_api, "retrieve_chunks", lambda **kwargs: [])

    response = client.post(
        "/chat",
        json={"question": "질문"},
    )

    assert response.status_code == 200
    assert response.json()["sources"] == []
    assert "자료" in response.json()["answer"]
