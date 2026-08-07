from dataclasses import dataclass
import json
import logging
import re
from pathlib import Path

from app.clients.vllm_client import VLLMClient


logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "retrieval_query_rewriter_system_prompt.txt"
MAX_PREVIOUS_QUESTION_CHARS = 500
MAX_PREVIOUS_ANSWER_CHARS = 1000
MAX_RETRIEVAL_QUERY_CHARS = 500
MAX_RETRIEVAL_QUERIES = 6
MAX_LOCAL_RETRIEVAL_QUERIES = 4
MAX_EVIDENCE_GOALS = 4
QUERY_LABEL_PATTERN = re.compile(
    r"^(?:검색\s*질의|독립형\s*(?:검색\s*)?질의|standalone\s+(?:retrieval\s+)?query)\s*:\s*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RetrievalQueryPlan:
    standalone_query: str
    queries: tuple[str, ...]
    evidence_goals: tuple[str, ...] = ()


def rewrite_retrieval_query(question: str, history: list[dict[str, str]]) -> str:
    return plan_retrieval_queries(question, history).standalone_query


def plan_retrieval_queries(question: str, history: list[dict[str, str]]) -> RetrievalQueryPlan:
    original_question = question.strip()
    previous_exchange = _latest_exchange(history)

    messages = [
        {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
        *previous_exchange,
        {
            "role": "user",
            "content": f"[현재 질문]\n{original_question}\n\n[검색 계획]",
        },
    ]
    client = VLLMClient()
    rewritten = ""
    try:
        rewritten = client.chat_completion(
            messages,
            temperature=0.0,
            operation="query_rewrite",
        )
        return _normalize_query_plan(rewritten, original_question, fallback_on_error=False)
    except Exception:
        logger.warning("Retrieval query planning failed; attempting one format repair")
    if "{" not in rewritten and "[" not in rewritten:
        normalized = _normalize_rewritten_query(rewritten, original_question)
        if normalized != rewritten.strip() or QUERY_LABEL_PATTERN.match(rewritten.strip()):
            return _fallback_plan(normalized)
    try:
        repaired = client.chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "Return one valid JSON object only. Required keys: standalone_query "
                        "(string), evidence_goals (1-4 strings), queries (1-4 strings), "
                        "cross_language_queries (0-2 strings). Do not answer the question."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question: {original_question}\n\n"
                        f"Malformed plan:\n{rewritten[:2000]}\n\nRepaired JSON:"
                    ),
                },
            ],
            temperature=0.0,
            operation="query_rewrite_repair",
        )
        return _normalize_query_plan(repaired, original_question, fallback_on_error=False)
    except Exception:
        logger.warning("Retrieval query plan repair failed; using the original question")
        return _fallback_plan(original_question)


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


def _normalize_query_plan(
    response: str,
    fallback: str,
    *,
    fallback_on_error: bool = True,
) -> RetrievalQueryPlan:
    try:
        payload = _parse_query_plan(response)
    except (json.JSONDecodeError, TypeError, ValueError):
        if not fallback_on_error:
            raise
        logger.warning("Invalid retrieval query plan; using a single normalized query")
        normalized = (
            _normalize_rewritten_query(response, fallback)
            if "{" not in response and "[" not in response
            else fallback
        )
        return _fallback_plan(normalized)

    standalone_query = _normalize_query_value(payload.get("standalone_query")) or fallback
    raw_queries = payload.get("queries")
    if not isinstance(raw_queries, list):
        raw_queries = []
    raw_goals = payload.get("evidence_goals")
    if not isinstance(raw_goals, list):
        raw_goals = raw_queries
    raw_cross_language_queries = payload.get("cross_language_queries")
    if not isinstance(raw_cross_language_queries, list):
        raw_cross_language_queries = [payload.get("cross_language_query")]
    cross_language_queries = _deduplicate_queries(
        [_normalize_query_value(query) for query in raw_cross_language_queries]
    )[:2]

    evidence_goals = _deduplicate_queries(
        [_normalize_query_value(goal) for goal in raw_goals]
    )
    if not evidence_goals:
        evidence_goals = [standalone_query]
    base_queries = _deduplicate_queries(
        [
            standalone_query,
            *(_normalize_query_value(query) for query in raw_queries),
        ]
    )
    cross_keys = {query.casefold() for query in cross_language_queries}
    base_queries = [query for query in base_queries if query.casefold() not in cross_keys]
    retained_base_count = min(
        MAX_LOCAL_RETRIEVAL_QUERIES,
        MAX_RETRIEVAL_QUERIES - len(cross_language_queries),
    )
    queries = [*base_queries[:retained_base_count], *cross_language_queries]
    return RetrievalQueryPlan(
        standalone_query=standalone_query,
        queries=tuple(queries[:MAX_RETRIEVAL_QUERIES]),
        evidence_goals=tuple(evidence_goals[:MAX_EVIDENCE_GOALS]),
    )


def _parse_query_plan(response: str) -> dict:
    try:
        return _parse_json_object(response)
    except ValueError:
        return _parse_tagged_plan(response)


def _parse_json_object(response: str) -> dict:
    candidate = response.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    decoder = json.JSONDecoder()
    payloads: list[dict] = []
    for start, character in enumerate(candidate):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(candidate[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    if not payloads:
        raise ValueError("JSON object not found")
    return max(payloads, key=_query_plan_payload_score)


def _parse_tagged_plan(response: str) -> dict:
    standalone_query = ""
    queries: list[str] = []
    evidence_goals: list[str] = []
    cross_language_query = ""
    cross_language_queries: list[str] = []
    for line in response.splitlines():
        key, separator, value = line.strip().partition(":")
        if not separator or not value.strip():
            continue
        if key.strip().upper() == "STANDALONE":
            standalone_query = value.strip()
        elif key.strip().upper() == "QUERY":
            queries.append(value.strip())
        elif key.strip().upper() == "GOAL":
            evidence_goals.append(value.strip())
        elif key.strip().upper() == "CROSS_LANGUAGE_QUERY":
            cross_language_query = value.strip()
            cross_language_queries.append(value.strip())
    if not standalone_query and not queries:
        raise ValueError("Tagged query plan not found")
    return {
        "standalone_query": standalone_query,
        "queries": queries,
        "evidence_goals": evidence_goals,
        "cross_language_query": cross_language_query,
        "cross_language_queries": cross_language_queries,
    }


def _query_plan_payload_score(payload: dict) -> tuple[int, int]:
    queries = payload.get("queries")
    valid_query_count = (
        sum(isinstance(query, str) and bool(query.strip()) for query in queries)
        if isinstance(queries, list)
        else 0
    )
    has_standalone_query = int(bool(_normalize_query_value(payload.get("standalone_query"))))
    return valid_query_count, has_standalone_query


def _normalize_query_value(value) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())[:MAX_RETRIEVAL_QUERY_CHARS].rstrip()


def _deduplicate_queries(queries) -> list[str]:
    unique_queries: list[str] = []
    seen: set[str] = set()
    for query in queries:
        if not query:
            continue
        key = query.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique_queries.append(query)
    return unique_queries


def _fallback_plan(question: str) -> RetrievalQueryPlan:
    return RetrievalQueryPlan(
        standalone_query=question,
        queries=(question,),
        evidence_goals=(question,),
    )
