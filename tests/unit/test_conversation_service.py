from dataclasses import dataclass

from app.services.conversation_service import build_conversation_context


@dataclass(frozen=True)
class StubMessage:
    role: str
    content: str


def test_build_conversation_context_keeps_recent_supported_messages() -> None:
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
    messages = [
        StubMessage("user", "가" * 6000),
        StubMessage("assistant", "나" * 6000),
    ]

    context = build_conversation_context(messages)

    assert sum(len(message["content"]) for message in context) == 8000
    assert context[0]["content"] == "가" * 2000
    assert context[1]["content"] == "나" * 6000
