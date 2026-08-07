from app.services.prompt_builder import (
    build_rag_messages,
    build_system_message,
    build_user_message,
)
from app.services.retriever import RetrievedChunk


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=1,
        document_id=2,
        document_title="guide.pdf",
        content="버전 관리는 변경 이력을 기록한다.",
        page_start=3,
        page_end=3,
        score=0.9,
        source_refs={"page": 3},
    )


def test_build_role_messages_use_generic_rag_contract() -> None:
    system_message = build_system_message()
    user_message = build_user_message("핵심은?", [_chunk()])

    assert system_message["role"] == "system"
    assert "범용 RAG 어시스턴트" in system_message["content"]
    assert "간호" not in system_message["content"]
    assert user_message["role"] == "user"
    assert "[Source 1]" in user_message["content"]
    assert "[Question]\n핵심은?" in user_message["content"]


def test_system_prompt_allows_only_fully_supported_multi_source_inference() -> None:
    content = build_system_message()["content"]

    assert "여러 Context에 모두 명시" in content
    assert "결론이 직접 도출" in content
    assert "자료에 없는 중간 전제" in content
    assert "필요한 전제가 하나라도 Context에 없어서" in content
    assert "각 사실이나 비교 항목 바로 뒤" in content
    assert "비교 대상 양쪽의 근거" in content


def test_build_rag_messages_places_history_before_current_question() -> None:
    messages = build_rag_messages(
        "그 다음은?",
        [_chunk()],
        [
            {"role": "user", "content": "먼저 무엇을 하나요?"},
            {"role": "assistant", "content": "위험 요인을 확인합니다."},
        ],
    )

    assert [message["role"] for message in messages] == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "먼저 무엇을 하나요?"
    assert "[Context]" in messages[-1]["content"]
    assert "그 다음은?" in messages[-1]["content"]
