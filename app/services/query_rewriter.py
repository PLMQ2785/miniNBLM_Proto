from dataclasses import dataclass
import json
import logging
import re
from pathlib import Path

from app.clients.llm_client import LLMClient


logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "retrieval_query_rewriter_system_prompt.txt"
MAX_PREVIOUS_QUESTION_CHARS = 500
MAX_PREVIOUS_ANSWER_CHARS = 1000
MAX_RETRIEVAL_QUERY_CHARS = 500
MAX_RETRIEVAL_QUERIES = 6
MAX_EVIDENCE_GOALS = 4
MAX_QUERIES_PER_GOAL = 3
JSON_OBJECT_RESPONSE_FORMAT = {"type": "json_object"}
GOAL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
QUERY_LABEL_PATTERN = re.compile(
    r"^(?:검색\s*질의|독립형\s*(?:검색\s*)?질의|standalone\s+(?:retrieval\s+)?query)\s*:\s*",
    re.IGNORECASE,
)
STRUCTURED_FRAGMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\$?\s*:\s*[\[\{]\s*$")


@dataclass(frozen=True)
class EvidenceGoal:
    goal_id: str
    description: str
    queries: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalQueryPlan:
    standalone_query: str
    goals: tuple[EvidenceGoal, ...]

    @property
    def queries(self) -> tuple[str, ...]:
        return tuple(
            _deduplicate_queries(
                [self.standalone_query, *(query for goal in self.goals for query in goal.queries)]
            )[:MAX_RETRIEVAL_QUERIES]
        )


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
    client = LLMClient()
    rewritten = ""
    try:
        rewritten = client.chat_completion(
            messages,
            temperature=0.0,
            operation="query_rewrite",
            response_format=JSON_OBJECT_RESPONSE_FORMAT,
        )
        return _normalize_query_plan(rewritten, original_question)
    except Exception:
        logger.warning("Retrieval query planning failed; attempting one format repair")

    try:
        repaired = client.chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "Return one valid JSON object only. Required keys: standalone_query "
                        "(string) and evidence_goals (1-4 objects). Every goal object requires "
                        "a unique goal_id, description, and queries (1-3 strings). Do not answer."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Conversation context:\n{_format_exchange(previous_exchange)}\n\n"
                        f"Current question: {original_question}\n\n"
                        f"Malformed plan:\n{rewritten[:2000]}\n\nRepaired JSON:"
                    ),
                },
            ],
            temperature=0.0,
            operation="query_rewrite_repair",
            response_format=JSON_OBJECT_RESPONSE_FORMAT,
        )
        return _normalize_query_plan(repaired, original_question)
    except Exception:
        logger.warning("Retrieval query plan repair failed; using a safe fallback query")
        if "{" not in rewritten and "[" not in rewritten:
            normalized = _normalize_rewritten_query(rewritten, original_question)
            if normalized != rewritten.strip() or QUERY_LABEL_PATTERN.match(rewritten.strip()):
                return _fallback_plan(normalized)
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


def _format_exchange(exchange: list[dict[str, str]]) -> str:
    if not exchange:
        return "(none)"
    return "\n".join(f"[{message['role']}] {message['content']}" for message in exchange)


def _normalize_rewritten_query(rewritten: str, fallback: str) -> str:
    lines = [line.strip() for line in rewritten.strip().splitlines() if line.strip()]
    lines = [line for line in lines if not line.startswith("```")]
    if not lines:
        return fallback
    candidate = " ".join(lines)
    candidate = QUERY_LABEL_PATTERN.sub("", candidate).strip().strip('"\'')
    return (candidate or fallback)[:MAX_RETRIEVAL_QUERY_CHARS].rstrip()


def _goal_object(raw_goal: dict) -> dict:
    has_goal_fields = any(
        key.casefold().startswith(("goal", "description", "quer"))
        and not isinstance(value, dict)
        for key, value in raw_goal.items()
    )
    if has_goal_fields:
        return raw_goal
    nested_goals = [
        value
        for key, value in raw_goal.items()
        if key.casefold().startswith("goal") and isinstance(value, dict)
    ]
    return nested_goals[0] if len(nested_goals) == 1 else raw_goal


def _goal_field(raw_goal: dict, name: str) -> object | None:
    value = raw_goal.get(name)
    if value is not None:
        return value
    for key, candidate in raw_goal.items():
        if key.casefold().startswith(name.casefold()):
            return candidate
    return None


def _goal_id(raw_goal: dict, position: int) -> str:
    value = _goal_field(raw_goal, "goal_id")
    if value is None:
        value = next(
            (
                candidate
                for key, candidate in raw_goal.items()
                if key.casefold().startswith("goal") and isinstance(candidate, str)
            ),
            None,
        )
    goal_id = str(value or "").strip().casefold()
    return goal_id if GOAL_ID_PATTERN.fullmatch(goal_id) else f"g{position}"


def _goal_queries(raw_goal: dict) -> list[str]:
    value = _goal_field(raw_goal, "queries")
    raw_queries = value if isinstance(value, list) else [value]
    return _deduplicate_queries(
        [_normalize_query_value(query) for query in raw_queries if query is not None]
    )[:MAX_QUERIES_PER_GOAL]


def _normalize_query_plan(response: str, fallback: str) -> RetrievalQueryPlan:
    payload = _parse_json_object(response)
    standalone_query = _normalize_query_value(payload.get("standalone_query")) or fallback
    raw_goals = payload.get("evidence_goals")
    if not isinstance(raw_goals, list) or not raw_goals:
        raise ValueError("evidence_goals must contain goal objects")

    parsed_goals: list[tuple[str, str, list[str]]] = []
    seen_ids: set[str] = set()
    for position, raw_goal in enumerate(
        raw_goals[:MAX_EVIDENCE_GOALS],
        start=1,
    ):
        if not isinstance(raw_goal, dict):
            raise ValueError("Every evidence goal must be an object")
        normalized_goal = _goal_object(raw_goal)
        goal_id = _goal_id(normalized_goal, position)
        if goal_id in seen_ids:
            raise ValueError("Evidence goal IDs must be unique")
        queries = _goal_queries(normalized_goal)
        if not queries:
            raise ValueError("Every evidence goal requires a search query")
        description = (
            _normalize_query_value(_goal_field(normalized_goal, "description"))
            or queries[0]
        )
        seen_ids.add(goal_id)
        parsed_goals.append((goal_id, description, queries))

    if not parsed_goals:
        raise ValueError("At least one evidence goal is required")
    allocated = [[queries[0]] for _, _, queries in parsed_goals]
    remaining_query_slots = MAX_RETRIEVAL_QUERIES - 1 - len(allocated)
    query_offset = 1
    while remaining_query_slots > 0:
        added = False
        for allocation, (_, _, queries) in zip(allocated, parsed_goals, strict=True):
            if query_offset < len(queries):
                allocation.append(queries[query_offset])
                remaining_query_slots -= 1
                added = True
                if remaining_query_slots == 0:
                    break
        if not added:
            break
        query_offset += 1
    goals = tuple(
        EvidenceGoal(goal_id, description, tuple(queries))
        for (goal_id, description, _), queries in zip(
            parsed_goals,
            allocated,
            strict=True,
        )
    )
    return RetrievalQueryPlan(standalone_query=standalone_query, goals=goals)


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


def _query_plan_payload_score(payload: dict) -> tuple[int, int]:
    goals = payload.get("evidence_goals")
    if not isinstance(goals, list):
        return (0, 0)
    query_count = sum(
        len(goal.get("queries", []))
        for goal in goals
        if isinstance(goal, dict) and isinstance(goal.get("queries"), list)
    )
    return (len(goals), query_count)


def _normalize_query_value(value) -> str:
    if not isinstance(value, str):
        return ""
    normalized = " ".join(value.split()).strip().strip('"\'')
    if not normalized or STRUCTURED_FRAGMENT_PATTERN.match(normalized):
        return ""
    return normalized[:MAX_RETRIEVAL_QUERY_CHARS].rstrip()


def _deduplicate_queries(queries: list[str]) -> list[str]:
    deduplicated: list[str] = []
    seen: set[str] = set()
    for query in queries:
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        deduplicated.append(query)
    return deduplicated


def _fallback_plan(question: str) -> RetrievalQueryPlan:
    return RetrievalQueryPlan(
        standalone_query=question,
        goals=(EvidenceGoal("g1", question, (question,)),),
    )
