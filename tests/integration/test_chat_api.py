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
        document_title=document.title,
        content="낙상 발생 시 환자를 바로 일으키지 않고 손상 여부를 확인한다.",
        page_start=4,
        page_end=4,
        score=0.9,
        source_refs={"page": 4},
    )
    retrieval_calls = []
    generation_calls = []
    rewritten_query = "낙상 후 손상 여부를 확인한 다음 조치"

    def retrieve_for_workspace(**kwargs):
        retrieval_calls.append(kwargs)
        return [retrieved]

    monkeypatch.setattr(chat_api, "retrieve_chunks", retrieve_for_workspace)

    def rewrite_for_retrieval(question, history):
        return rewritten_query if history else question

    monkeypatch.setattr(chat_api, "rewrite_retrieval_query", rewrite_for_retrieval)

    def generate_with_history(**kwargs):
        generation_calls.append(kwargs)
        return GeneratedAnswer(
            answer="손상 여부를 먼저 확인합니다.",
            sources=[
                SourceRef(
                    document_id=document.id,
                    document_title=document.title,
                    page=4,
                    chunk_id=101,
                )
            ],
        )

    monkeypatch.setattr(chat_api, "generate_answer", generate_with_history)

    response = client.post(
        "/chat",
        json={"question": "낙상 후 무엇을 먼저 하나요?"},
    )

    assert response.status_code == 200
    session_id = response.json()["session"]["session_id"]
    assert response.json()["session"]["title"] == "낙상 후 무엇을 먼저 하나요?"
    assert response.json()["sources"] == [
        {
            "document_id": document.id,
            "document_title": document.title,
            "page": 4,
            "chunk_id": 101,
            "available": True,
        }
    ]
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ChatSession)) == 1
    assert db.scalar(select(func.count()).select_from(ChatMessage)) == 2
    session = db.scalar(select(ChatSession))
    assert session.owner_id == user.id
    assert session.document_id is None
    assert retrieval_calls[0]["owner_id"] == user.id
    assert retrieval_calls[0]["question"] == "낙상 후 무엇을 먼저 하나요?"
    assert "document_id" not in retrieval_calls[0]
    assert generation_calls[0]["history"] == []

    follow_up = client.post(
        "/chat",
        json={"session_id": session_id, "question": "그 다음에는 무엇을 하나요?"},
    )

    assert follow_up.status_code == 200
    assert follow_up.json()["session"]["session_id"] == session_id
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ChatSession)) == 1
    assert db.scalar(select(func.count()).select_from(ChatMessage)) == 4
    assert generation_calls[1]["history"] == [
        {"role": "user", "content": "낙상 후 무엇을 먼저 하나요?"},
        {"role": "assistant", "content": "손상 여부를 먼저 확인합니다."},
    ]
    assert retrieval_calls[1]["question"] == rewritten_query
    assert generation_calls[1]["question"] == "그 다음에는 무엇을 하나요?"

    session_list = client.get("/chat/sessions")
    assert session_list.status_code == 200
    assert [item["session_id"] for item in session_list.json()["sessions"]] == [session_id]

    session_detail = client.get(f"/chat/sessions/{session_id}?limit=2")
    assert session_detail.status_code == 200
    assert session_detail.json()["has_more"] is True
    assert [message["role"] for message in session_detail.json()["messages"]] == ["user", "assistant"]
    assert session_detail.json()["messages"][1]["sources"][0]["available"] is True

    first_loaded_id = session_detail.json()["messages"][0]["message_id"]
    older_messages = client.get(
        f"/chat/sessions/{session_id}?limit=2&before_id={first_loaded_id}"
    )
    assert older_messages.status_code == 200
    assert older_messages.json()["has_more"] is False
    assert older_messages.json()["messages"][0]["content"] == "낙상 후 무엇을 먼저 하나요?"

    assert client.delete(f"/documents/{document.id}").status_code == 204
    history_after_document_delete = client.get(f"/chat/sessions/{session_id}").json()
    source = history_after_document_delete["messages"][1]["sources"][0]
    assert source["document_title"] == document.title
    assert source["available"] is False


def test_chat_sessions_are_isolated_and_can_be_deleted(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert client.post(
        "/auth/register",
        json={"username": "session-owner", "password": "password123"},
    ).status_code == 201
    monkeypatch.setattr(chat_api, "retrieve_chunks", lambda **kwargs: [])

    created = client.post("/chat", json={"question": "내 대화"})
    assert created.status_code == 200
    session_id = created.json()["session"]["session_id"]

    with TestClient(client.app) as other:
        assert other.post(
            "/auth/register",
            json={"username": "other-session-user", "password": "password123"},
        ).status_code == 201
        assert other.get("/chat/sessions").json() == {"sessions": []}
        assert other.get(f"/chat/sessions/{session_id}").status_code == 404
        assert other.delete(f"/chat/sessions/{session_id}").status_code == 404
        assert other.post(
            "/chat",
            json={"session_id": session_id, "question": "가로채기"},
        ).status_code == 404

    assert client.delete(f"/chat/sessions/{session_id}").status_code == 204
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ChatSession)) == 0
    assert db.scalar(select(func.count()).select_from(ChatMessage)) == 0


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
