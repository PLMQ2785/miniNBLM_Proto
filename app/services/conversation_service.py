from collections.abc import Sequence

from app.models.chat import ChatMessage


MAX_CONTEXT_MESSAGES = 8
MAX_CONTEXT_CHARS = 8000


def build_conversation_context(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    """최근 대화를 최신 내용 우선으로 8,000자 안에 맞춰 모델 이력으로 만든다."""
    history = [
        {"role": message.role, "content": message.content}
        for message in messages[-MAX_CONTEXT_MESSAGES:]
        if message.role in {"user", "assistant"} and message.content
    ]
    return limit_conversation_context(history, MAX_CONTEXT_CHARS)


def limit_conversation_context(
    history: Sequence[dict[str, str]],
    max_chars: int,
) -> list[dict[str, str]]:
    """이미 정규화된 대화 이력을 최신 내용부터 지정 문자 수에 맞춘다."""
    if max_chars <= 0:
        return []
    selected: list[dict[str, str]] = []
    remaining_chars = max_chars
    for message in reversed(history):
        role = message.get("role")
        content = message.get("content", "")
        if role not in {"user", "assistant"} or not content:
            continue
        if len(content) > remaining_chars:
            content = content[-remaining_chars:]
        if not content:
            break
        selected.append({"role": role, "content": content})
        remaining_chars -= len(content)
        if remaining_chars <= 0:
            break
    return list(reversed(selected))
