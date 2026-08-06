import logging
import re
from pathlib import Path

from app.clients.vllm_client import VLLMClient


logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "retrieval_query_rewriter_system_prompt.txt"
MAX_PREVIOUS_QUESTION_CHARS = 500
MAX_PREVIOUS_ANSWER_CHARS = 1000
MAX_RETRIEVAL_QUERY_CHARS = 500
QUERY_LABEL_PATTERN = re.compile(
    r"^(?:검색\s*질의|독립형\s*(?:검색\s*)?질의|standalone\s+(?:retrieval\s+)?query)\s*:\s*",
    re.IGNORECASE,
)


def rewrite_retrieval_query(question: str, history: list[dict[str, str]]) -> str:
    original_question = question.strip()
    previous_exchange = _latest_exchange(history)
    if not previous_exchange:
        return original_question

    messages = [
        {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
        *previous_exchange,
        {
            "role": "user",
            "content": f"[현재 질문]\n{original_question}\n\n[독립형 검색 질의]",
        },
    ]
    try:
        rewritten = VLLMClient().chat_completion(
            messages,
            temperature=0.0,
            operation="query_rewrite",
        )
    except Exception:
        logger.warning("Retrieval query rewriting failed; using the original question", exc_info=True)
        return original_question
    return _normalize_rewritten_query(rewritten, original_question)


def _latest_exchange(history: list[dict[str, str]]) -> list[dict[str, str]]:
    previous_user: str | None = None
    previous_assistant: str | None = None

    for message in reversed(history):
        role = message.get("role")
        content = message.get("content", "").strip()
        if not content:
            continue
        if role == "assistant" and previous_assistant is None:
            previous_assistant = content[:MAX_PREVIOUS_ANSWER_CHARS]
        elif role == "user":
            previous_user = content[:MAX_PREVIOUS_QUESTION_CHARS]
            break

    exchange: list[dict[str, str]] = []
    if previous_user:
        exchange.append({"role": "user", "content": previous_user})
    if previous_assistant:
        exchange.append({"role": "assistant", "content": previous_assistant})
    return exchange


def _normalize_rewritten_query(rewritten: str, fallback: str) -> str:
    lines = [line.strip() for line in rewritten.strip().splitlines() if line.strip()]
    lines = [line for line in lines if not line.startswith("```")]
    if not lines:
        return fallback

    candidate = " ".join(lines)
    candidate = QUERY_LABEL_PATTERN.sub("", candidate).strip().strip('"\'')
    if not candidate:
        return fallback
    return candidate[:MAX_RETRIEVAL_QUERY_CHARS].rstrip()
