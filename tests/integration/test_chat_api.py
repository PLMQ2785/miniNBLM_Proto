import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import chat as chat_api
from app.models.chat import ChatMessage, ChatSession
from app.repositories import user_repository
from app.schemas.chat import SourceRef
from app.services.generator import GeneratedAnswer
from app.clients.llm_client import LLMClient
from app.services.query_rewriter import RetrievalQueryPlan
from app.services.retriever import RetrievedChunk


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def stub_query_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        chat_api,
        "plan_retrieval_queries",
        lambda question, history: RetrievalQueryPlan(question.strip(), (question.strip(),)),
    )
    monkeypatch.setattr(
        chat_api,
        "complete_evidence_coverage",
        lambda **kwargs: kwargs["chunks"],
    )


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

    def plan_for_retrieval(question, history):
        query = rewritten_query if history else question
        return RetrievalQueryPlan(query, (query,))

    monkeypatch.setattr(chat_api, "plan_retrieval_queries", plan_for_retrieval)

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
    assistant_message = db.scalar(select(ChatMessage).where(ChatMessage.role == "assistant"))
    assert assistant_message is not None
    trace = assistant_message.message_metadata["retrieval_trace"]
    assert trace["query_plan"]["queries"] == ["낙상 후 무엇을 먼저 하나요?"]
    assert trace["outcome"]["status"] == "grounded"
    assert trace["outcome"]["final_chunk_ids"] == [101]
    session = db.scalar(select(ChatSession))
    assert session.owner_id == user.id
    assert session.document_id is None
    assert retrieval_calls[0]["owner_id"] == user.id
    assert retrieval_calls[0]["question"] == "낙상 후 무엇을 먼저 하나요?"
    assert retrieval_calls[0]["queries"] == ("낙상 후 무엇을 먼저 하나요?",)
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
    assert retrieval_calls[1]["queries"] == (rewritten_query,)
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


def test_legacy_chat_history_filters_retrieval_candidates_by_citation(
    client: TestClient,
    db: Session,
    document_factory,
) -> None:
    assert client.post(
        "/auth/register",
        json={"username": "legacy-sources", "password": "password123"},
    ).status_code == 201
    user = user_repository.get_user_by_username(db, "legacy-sources")
    candidate = document_factory(user, title="candidate.pdf")
    cited = document_factory(user, title="cited.pdf")
    session = ChatSession(owner_id=user.id, title="기존 대화")
    db.add(session)
    db.flush()
    db.add(
        ChatMessage(
            session_id=session.id,
            role="assistant",
            content="실제로 참고한 내용입니다. [Source 2, Page 9]",
            message_metadata={
                "sources": [
                    {
                        "document_id": candidate.id,
                        "document_title": candidate.title,
                        "page": 3,
                        "chunk_id": 101,
                    },
                    {
                        "document_id": cited.id,
                        "document_title": cited.title,
                        "page": 9,
                        "chunk_id": 102,
                    },
                ]
            },
        )
    )
    db.commit()

    response = client.get(f"/chat/sessions/{session.id}")

    assert response.status_code == 200
    sources = response.json()["messages"][0]["sources"]
    assert len(sources) == 1
    assert sources[0]["document_id"] == cited.id
    assert sources[0]["document_title"] == "cited.pdf"
    assert sources[0]["page"] == 9


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


def test_chat_streams_answer_and_persists_only_after_completion(
    client: TestClient,
    db: Session,
    document_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert client.post(
        "/auth/register",
        json={"username": "stream-user", "password": "password123"},
    ).status_code == 201
    user = user_repository.get_user_by_username(db, "stream-user")
    document = document_factory(user)
    retrieved = RetrievedChunk(
        chunk_id=501,
        document_id=document.id,
        document_title=document.title,
        content="낙상 후 손상 여부를 확인한다.",
        page_start=7,
        page_end=7,
        score=0.9,
        source_refs={"page": 7},
    )
    monkeypatch.setattr(chat_api, "retrieve_chunks", lambda **kwargs: [retrieved])
    monkeypatch.setattr(
        LLMClient,
        "stream_chat_completion",
        lambda self, messages, **kwargs: iter(
            ["손상 여부를 ", "확인합니다. [Source 1, Page 7]"]
        ),
    )

    with client.stream("POST", "/chat/stream", json={"question": "낙상 후 조치는?"}) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: session" in body
    assert 'event: delta\ndata: {"text": "손상 여부를 "}' in body
    assert "event: sources" in body
    assert '"document_title": "' + document.title + '"' in body
    assert "event: done" in body
    db.expire_all()
    messages = list(db.scalars(select(ChatMessage).order_by(ChatMessage.id)))
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[1].content == "손상 여부를 확인합니다. [Source 1, Page 7]"


def test_chat_stream_hides_fragmented_no_source_marker(
    client: TestClient,
    db: Session,
    document_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert client.post(
        "/auth/register",
        json={"username": "no-source-stream", "password": "password123"},
    ).status_code == 201
    user = user_repository.get_user_by_username(db, "no-source-stream")
    document = document_factory(user)
    retrieved = RetrievedChunk(
        chunk_id=551,
        document_id=document.id,
        document_title=document.title,
        content="질문과 관련 없는 검색 결과",
        page_start=3,
        page_end=3,
        score=0.4,
        source_refs={"page": 3},
    )
    monkeypatch.setattr(chat_api, "retrieve_chunks", lambda **kwargs: [retrieved])
    monkeypatch.setattr(
        LLMClient,
        "stream_chat_completion",
        lambda self, messages, **kwargs: iter(
            ["[[NO_", "SOURCE]] 업로드된 자료에서 확인되지 않습니다."]
        ),
    )

    with client.stream("POST", "/chat/stream", json={"question": "자료 밖 질문"}) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "NO_SOURCE" not in body
    assert "업로드된 자료에서 확인되지 않습니다." in body
    assert "event: sources\ndata: []" in body
    assert "event: done" in body
    db.expire_all()
    assistant = db.scalar(select(ChatMessage).where(ChatMessage.role == "assistant"))
    assert assistant is not None
    assert "NO_SOURCE" not in assistant.content
    assert assistant.message_metadata["sources"] == []
    assert assistant.message_metadata["source_selection"] == "cited"
    assert assistant.message_metadata["retrieval_trace"]["outcome"]["status"] == "no_source"


def test_chat_stream_revises_and_persists_citation_repair(
    client: TestClient,
    db: Session,
    document_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert client.post(
        "/auth/register",
        json={"username": "citation-revision", "password": "password123"},
    ).status_code == 201
    user = user_repository.get_user_by_username(db, "citation-revision")
    document = document_factory(user)
    retrieved = RetrievedChunk(
        chunk_id=571,
        document_id=document.id,
        document_title=document.title,
        content="낙상 후 손상 여부를 확인한다.",
        page_start=7,
        page_end=7,
        score=0.9,
        source_refs={"page": 7},
    )
    monkeypatch.setattr(chat_api, "retrieve_chunks", lambda **kwargs: [retrieved])
    monkeypatch.setattr(
        LLMClient,
        "stream_chat_completion",
        lambda self, messages, **kwargs: iter(["낙상 후 손상 여부를 확인합니다."]),
    )
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda self, messages, **kwargs: (
            "낙상 후 손상 여부를 확인합니다. [Source 1, Page 7]"
        ),
    )

    with client.stream("POST", "/chat/stream", json={"question": "낙상 후 조치는?"}) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: revision" in body
    assert "[Source 1, Page 7]" in body
    db.expire_all()
    assistant = db.scalar(select(ChatMessage).where(ChatMessage.role == "assistant"))
    assert assistant is not None
    assert assistant.content.endswith("[Source 1, Page 7]")
    assert assistant.message_metadata["sources"][0]["page"] == 7


def test_failed_new_chat_stream_removes_empty_session(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert client.post(
        "/auth/register",
        json={"username": "failed-stream", "password": "password123"},
    ).status_code == 201
    retrieved = RetrievedChunk(
        chunk_id=601,
        document_id=1,
        document_title="lesson.pdf",
        content="검색 결과",
        page_start=1,
        page_end=1,
        score=0.5,
        source_refs={},
    )
    monkeypatch.setattr(chat_api, "retrieve_chunks", lambda **kwargs: [retrieved])

    def fail_stream(*args, **kwargs):
        raise RuntimeError("vLLM failed")

    monkeypatch.setattr(LLMClient, "stream_chat_completion", fail_stream)

    with client.stream("POST", "/chat/stream", json={"question": "실패 질문"}) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: error" in body
    assert "request_id" in body
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ChatSession)) == 0
    assert db.scalar(select(func.count()).select_from(ChatMessage)) == 0
