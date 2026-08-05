from app.services.prompt_builder import build_tutor_messages
from app.services.retriever import RetrievedChunk


def test_build_tutor_messages_places_history_before_current_rag_question() -> None:
    chunk = RetrievedChunk(
        chunk_id=1,
        document_id=2,
        document_title="lesson.pdf",
        content="낙상 예방 교육",
        page_start=3,
        page_end=3,
        score=0.9,
        source_refs={"page": 3},
    )

    messages = build_tutor_messages(
        "그 다음은?",
        [chunk],
        [
            {"role": "user", "content": "먼저 무엇을 하나요?"},
            {"role": "assistant", "content": "위험 요인을 확인합니다."},
        ],
    )

    assert [message["role"] for message in messages] == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "먼저 무엇을 하나요?"
    assert "[Context]" in messages[-1]["content"]
    assert "그 다음은?" in messages[-1]["content"]
