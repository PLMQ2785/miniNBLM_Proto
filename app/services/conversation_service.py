from collections.abc import Sequence

from app.models.chat import ChatMessage


MAX_CONTEXT_MESSAGES = 8
MAX_CONTEXT_CHARS = 8000


def build_conversation_context(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    """최근 대화를 최신 내용 우선으로 8,000자 안에 맞춰 모델 이력으로 만든다."""
    selected: list[dict[str, str]] = []
    remaining_chars = MAX_CONTEXT_CHARS

    for message in reversed(messages[-MAX_CONTEXT_MESSAGES:]):
        if message.role not in {"user", "assistant"} or not message.content:
            continue
        content = message.content
        if len(content) > remaining_chars:
            content = content[-remaining_chars:]
        if not content:
            break
        selected.append({"role": message.role, "content": content})
        remaining_chars -= len(content)
        if remaining_chars <= 0:
            break

    return list(reversed(selected))
