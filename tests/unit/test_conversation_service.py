from dataclasses import dataclass

from app.services.conversation_service import (
    build_conversation_context,
    limit_conversation_context,
)


@dataclass(frozen=True)
class StubMessage:
    """대화 문맥 입력을 흉내 내는 최소 메시지 객체다."""
    role: str
    content: str


def test_build_conversation_context_keeps_recent_supported_messages() -> None:
    """지원 역할의 최근 메시지만 원래 순서로 문맥에 남긴다."""
    messages = [
        StubMessage("system", "ignore"),
        StubMessage("user", "첫 질문"),
        StubMessage("assistant", "첫 답변"),
        StubMessage("user", "후속 질문"),
    ]

    assert build_conversation_context(messages) == [
        {"role": "user", "content": "첫 질문"},
        {"role": "assistant", "content": "첫 답변"},
        {"role": "user", "content": "후속 질문"},
    ]


def test_build_conversation_context_limits_total_characters() -> None:
    """대화 문맥은 최근 내용을 우선해 전체 문자 제한을 지킨다."""
    messages = [
        StubMessage("user", "가" * 6000),
        StubMessage("assistant", "나" * 6000),
    ]

    context = build_conversation_context(messages)

    assert sum(len(message["content"]) for message in context) == 8000
    assert context[0]["content"] == "가" * 2000
    assert context[1]["content"] == "나" * 6000


def test_limit_conversation_context_supports_compact_and_empty_budgets() -> None:
    """복구 단계가 최신 이력만 남기거나 이력을 완전히 제거할 수 있게 한다."""
    history = [
        {"role": "user", "content": "이전 질문"},
        {"role": "assistant", "content": "가" * 3000},
    ]

    compact = limit_conversation_context(history, 1000)

    assert compact == [{"role": "assistant", "content": "가" * 1000}]
    assert limit_conversation_context(history, 0) == []
