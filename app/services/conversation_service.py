from collections.abc import Sequence

from app.models.chat import ChatMessage


MAX_CONTEXT_MESSAGES = 8
MAX_CONTEXT_CHARS = 8000


def build_conversation_context(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
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
