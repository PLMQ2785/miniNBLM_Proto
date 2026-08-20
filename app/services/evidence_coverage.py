from dataclasses import asdict, dataclass
import json
import logging
import re
import time
from pathlib import Path
from typing import Literal

from sqlalchemy.orm import Session

from app.clients.llm_client import LLMClient
from app.observability import (
    EVIDENCE_COVERAGE_DURATION,
    EVIDENCE_COVERAGE_REQUESTS,
    RETRIEVAL_RETRIES,
)
from app.services.hierarchical_retriever import retrieve_hierarchical_chunks
from app.services.query_rewriter import EvidenceGoal
from app.services.retrieval_trace import RetrievalTrace
from app.services.retriever import RetrievedChunk, retrieve_chunks


logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "evidence_coverage_system_prompt.txt"
MAX_COVERAGE_CONTEXT_CHARS = 18_000
MAX_RETRY_CONTEXT_CHUNKS = 16
JSON_OBJECT_RESPONSE_FORMAT = {"type": "json_object"}
MAX_RETRY_CONTEXT_CHARS = 24_000
MAX_RETRIEVAL_ACTIONS = 2
GOAL_STATUSES = {"supported", "partial", "missing", "contradicted"}


@dataclass(frozen=True)
class EvidenceReference:
    """목표 충족 판정이 인용한 실제 청크 위치를 보존한다."""
    chunk_id: int
    document_title: str
    page_start: int
    page_end: int


@dataclass(frozen=True)
class GoalCoverage:
    """목표별 근거 상태와 부족할 때의 재검색어를 전달한다."""
    goal_id: str
    description: str
    status: Literal["supported", "partial", "missing", "contradicted"]
    evidence: tuple[EvidenceReference, ...] = ()
    retry_queries: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceCoverageAssessment:
    """계획된 모든 목표의 근거 충족 판정을 묶는다."""
    goals: tuple[GoalCoverage, ...]

    @property
    def sufficient(self) -> bool:
        """모든 목표가 근거로 완전히 지원되는지 확인한다."""
        return bool(self.goals) and all(goal.status == "supported" for goal in self.goals)


@dataclass(frozen=True)
class EvidenceMatrixGoal:
    """생성 프롬프트에 넣을 목표별 상태와 근거를 나타낸다."""
    goal_id: str
    description: str
    status: str
    evidence: tuple[EvidenceReference, ...] = ()


@dataclass(frozen=True)
class EvidenceMatrix:
    """최신 충족도 판정을 생성 단계가 소비할 행렬로 전달한다."""
    status: Literal["complete", "partial", "insufficient", "unchecked"]
    goals: tuple[EvidenceMatrixGoal, ...]


def assess_evidence_coverage(
    goals: tuple[EvidenceGoal, ...],
    chunks: list[RetrievedChunk],
) -> EvidenceCoverageAssessment | None:
    """현재 청크가 각 근거 목표를 충족하는지 LLM으로 검증한다."""
    if not goals or not chunks:
        return None

    started_at = time.perf_counter()
    status = "error"
    try:
        prompt = _coverage_request(goals, chunks)
        response = LLMClient().chat_completion(
            [
                {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            operation="evidence_coverage",
            response_format=JSON_OBJECT_RESPONSE_FORMAT,
        )
        try:
            assessment = _parse_coverage_response(response, goals, chunks)
        except (TypeError, ValueError, json.JSONDecodeError):
            repaired = LLMClient().chat_completion(
                [
                    {
                        "role": "system",
                        "content": (
                            "Repair the supplied evidence assessment to the required JSON schema. "
                            "Preserve only listed goal IDs and chunk IDs. Output JSON only."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"{prompt}\n\nInvalid response:\n{response}",
                    },
                ],
                temperature=0.0,
                operation="evidence_coverage_repair",
                response_format=JSON_OBJECT_RESPONSE_FORMAT,
            )
            # 알 수 없는 ID를 위치로 맞추지 않고 미확인 행렬로 남기는 편이 안전하다.
            try:
                assessment = _parse_coverage_response(repaired, goals, chunks)
            except (TypeError, ValueError, json.JSONDecodeError):
                logger.info(
                    "Evidence coverage repair remained invalid; using unchecked matrix"
                )
                status = "unchecked"
                return None
        status = "sufficient" if assessment.sufficient else "insufficient"
        return assessment
    except Exception:
        logger.warning("Evidence coverage assessment failed", exc_info=True)
        return None
    finally:
        EVIDENCE_COVERAGE_REQUESTS.labels(status=status).inc()
        EVIDENCE_COVERAGE_DURATION.observe(time.perf_counter() - started_at)


def complete_evidence_coverage(
    *,
    db: Session,
    owner_id: int,
    question: str,
    goals: tuple[EvidenceGoal, ...],
    chunks: list[RetrievedChunk],
    trace: RetrievalTrace | None = None,
) -> list[RetrievedChunk]:
    """계층 폴백과 목표 재검색을 합쳐 최대 두 동작으로 근거를 보완한다."""
    if not goals:
        return chunks

    current_chunks = chunks
    # 계층 폴백과 목표 재검색은 두 번의 공용 동작 예산을 함께 쓴다.
    actions = 0
    if not current_chunks:
        hierarchy_queries = tuple(query for goal in goals for query in goal.queries)
        current_chunks = retrieve_hierarchical_chunks(
            db=db,
            owner_id=owner_id,
            queries=hierarchy_queries,
            trace=trace,
            trace_stage="hierarchical_retry_1",
        )
        actions += 1
        RETRIEVAL_RETRIES.labels(
            status="success" if current_chunks else "empty"
        ).inc()

    assessment = assess_evidence_coverage(goals, current_chunks)
    _record_assessment(trace, actions, goals, assessment)
    if assessment is None:
        if current_chunks or actions >= MAX_RETRIEVAL_ACTIONS:
            return current_chunks
        assessment = EvidenceCoverageAssessment(
            tuple(
                GoalCoverage(goal.goal_id, goal.description, "missing")
                for goal in goals
            )
        )
    elif assessment.sufficient:
        return current_chunks

    while actions < MAX_RETRIEVAL_ACTIONS:
        retry_goals = _retry_goals(goals, assessment)
        if not retry_goals:
            return current_chunks
        actions += 1
        supplemental = retrieve_chunks(
            db=db,
            owner_id=owner_id,
            question=question,
            goals=retry_goals,
            trace=trace,
            trace_stage=f"targeted_retry_{actions}",
        )
        RETRIEVAL_RETRIES.labels(
            status="success" if supplemental else "empty"
        ).inc()
        # 빈 재검색 결과는 이미 찾은 컨텍스트를 지우지 않는다.
        current_chunks = _merge_retry_chunks(current_chunks, supplemental)
        assessment = assess_evidence_coverage(goals, current_chunks)
        _record_assessment(trace, actions, goals, assessment)
        if assessment is None or assessment.sufficient:
            return current_chunks

    return current_chunks


def build_evidence_matrix(
    goals: tuple[EvidenceGoal, ...],
    trace: RetrievalTrace,
) -> EvidenceMatrix:
    """추적의 최신 목표 판정을 생성용 근거 행렬로 확정한다."""
    if not goals:
        return EvidenceMatrix(status="unchecked", goals=())

    latest_results = next(
        (
            event.get("goals", [])
            for event in reversed(trace.coverage_events)
            if event.get("goals")
        ),
        [],
    )
    results_by_id = {
        str(result.get("goal_id")): result
        for result in latest_results
        if isinstance(result, dict)
    }
    matrix_goals: list[EvidenceMatrixGoal] = []
    for goal in goals:
        result = results_by_id.get(goal.goal_id)
        if result is None:
            matrix_goals.append(
                EvidenceMatrixGoal(goal.goal_id, goal.description, "unchecked")
            )
            continue
        evidence = tuple(
            EvidenceReference(
                chunk_id=int(item["chunk_id"]),
                document_title=str(item["document_title"]),
                page_start=int(item["page_start"]),
                page_end=int(item["page_end"]),
            )
            for item in result.get("evidence", [])
        )
        matrix_goals.append(
            EvidenceMatrixGoal(
                goal.goal_id,
                goal.description,
                str(result["status"]),
                evidence,
            )
        )

    statuses = {goal.status for goal in matrix_goals}
    if statuses == {"supported"}:
        matrix_status = "complete"
    elif "supported" in statuses or "partial" in statuses:
        matrix_status = "partial"
    elif statuses == {"unchecked"}:
        matrix_status = "unchecked"
    else:
        matrix_status = "insufficient"
    return EvidenceMatrix(status=matrix_status, goals=tuple(matrix_goals))


def _coverage_request(
    goals: tuple[EvidenceGoal, ...],
    chunks: list[RetrievedChunk],
) -> str:
    """목표와 제한된 청크 본문을 충족도 판정 요청으로 만든다."""
    goal_lines = "\n".join(
        f'- goal_id="{goal.goal_id}": {goal.description}' for goal in goals
    )
    context_parts: list[str] = []
    used_chars = 0
    for chunk in chunks:
        block = (
            f'[Chunk id={chunk.chunk_id} document="{chunk.document_title}" '
            f"pages={chunk.page_start}-{chunk.page_end}]\n{chunk.content.strip()}"
        )
        if context_parts and used_chars + len(block) > MAX_COVERAGE_CONTEXT_CHARS:
            break
        context_parts.append(block)
        used_chars += len(block)
    context = "\n\n".join(context_parts)
    return f"Evidence goals:\n{goal_lines}\n\nRetrieved evidence:\n{context}"


def _parse_coverage_response(
    response: str,
    goals: tuple[EvidenceGoal, ...],
    chunks: list[RetrievedChunk],
) -> EvidenceCoverageAssessment:
    """모델 판정을 계획된 목표·청크 ID에 엄격히 연결한다."""
    payload = _parse_json_object(response)
    raw_results = payload.get("goals")
    if not isinstance(raw_results, list) or len(raw_results) != len(goals):
        raise ValueError("Evidence assessment must return every planned goal once")

    planned_by_id = {goal.goal_id: goal for goal in goals}
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    parsed: dict[str, GoalCoverage] = {}
    for raw in raw_results:
        if not isinstance(raw, dict):
            raise ValueError("Each goal assessment must be an object")
        raw_goal_id = raw.get("goal_id")
        goal_id = raw_goal_id.strip().casefold() if isinstance(raw_goal_id, str) else ""
        if goal_id not in planned_by_id or goal_id in parsed:
            raise ValueError("Evidence assessment contains an unknown goal_id")

        raw_chunk_ids = raw.get("evidence_chunk_ids", [])
        if not isinstance(raw_chunk_ids, list):
            raise ValueError("evidence_chunk_ids must be an array")
        chunk_ids: list[int] = []
        for raw_chunk_id in raw_chunk_ids:
            if isinstance(raw_chunk_id, str) and raw_chunk_id.isdecimal():
                raw_chunk_id = int(raw_chunk_id)
            if isinstance(raw_chunk_id, bool) or not isinstance(raw_chunk_id, int):
                raise ValueError("evidence_chunk_ids must contain integers")
            if raw_chunk_id not in chunks_by_id:
                raise ValueError("Evidence assessment contains an unknown chunk ID")
            if raw_chunk_id not in chunk_ids:
                chunk_ids.append(raw_chunk_id)

        status = raw.get("status")
        if isinstance(status, str):
            status = status.strip().casefold().replace(" ", "_").replace("-", "_")
        status = {
            "complete": "supported",
            "fully_supported": "supported",
            "sufficient": "supported",
            "partially_supported": "partial",
            "insufficient": "partial",
            "unsupported": "missing",
            "not_found": "missing",
        }.get(status, status)
        if status not in GOAL_STATUSES:
            raise ValueError("Evidence assessment contains an invalid status")
        if status in {"supported", "partial", "contradicted"} and not chunk_ids:
            raise ValueError(f"{status} goal must cite evidence")
        if status == "missing" and chunk_ids:
            raise ValueError("Missing goal cannot cite evidence")

        retry_queries = _normalize_retry_queries(raw.get("retry_queries", []))
        parsed[goal_id] = GoalCoverage(
            goal_id=goal_id,
            description=planned_by_id[goal_id].description,
            status=status,
            evidence=tuple(
                EvidenceReference(
                    chunk_id=chunk_id,
                    document_title=chunks_by_id[chunk_id].document_title,
                    page_start=chunks_by_id[chunk_id].page_start,
                    page_end=chunks_by_id[chunk_id].page_end,
                )
                for chunk_id in chunk_ids
            ),
            retry_queries=retry_queries,
        )

    if set(parsed) != set(planned_by_id):
        raise ValueError("Evidence assessment must return every planned goal exactly once")
    return EvidenceCoverageAssessment(tuple(parsed[goal.goal_id] for goal in goals))


def _parse_json_object(response: str) -> dict:
    """충족도 응답이 단일 JSON 객체인지 검증한다."""
    candidate = response.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise ValueError("Evidence assessment must be a JSON object")
    return payload


def _normalize_retry_queries(raw_queries) -> tuple[str, ...]:
    """재검색어를 중복 없이 목표당 세 개까지 정규화한다."""
    if not isinstance(raw_queries, list):
        raise ValueError("retry_queries must be an array")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in raw_queries:
        if not isinstance(value, str):
            raise ValueError("retry_queries must contain strings")
        query = " ".join(value.split())
        key = query.casefold()
        if query and key not in seen:
            normalized.append(query[:500])
            seen.add(key)
        if len(normalized) == 3:
            break
    return tuple(normalized)


def _retry_goals(
    planned_goals: tuple[EvidenceGoal, ...],
    assessment: EvidenceCoverageAssessment,
) -> tuple[EvidenceGoal, ...]:
    """지원되지 않은 목표만 모델 후보를 우선해 재검색 계획으로 만든다."""
    planned_by_id = {goal.goal_id: goal for goal in planned_goals}
    retries: list[EvidenceGoal] = []
    for result in assessment.goals:
        if result.status == "supported":
            continue
        planned = planned_by_id[result.goal_id]
        retries.append(
            EvidenceGoal(
                goal_id=planned.goal_id,
                description=planned.description,
                queries=result.retry_queries or planned.queries,
            )
        )
    return tuple(retries)


def _record_assessment(
    trace: RetrievalTrace | None,
    attempt: int,
    planned_goals: tuple[EvidenceGoal, ...],
    assessment: EvidenceCoverageAssessment | None,
) -> None:
    """목표별 충족도와 근거를 이후 행렬 생성용 추적에 남긴다."""
    if trace is None:
        return
    if assessment is None:
        trace.record_coverage(
            attempt=attempt,
            status="unchecked",
            goal_results=[
                {
                    "goal_id": goal.goal_id,
                    "description": goal.description,
                    "status": "unchecked",
                    "evidence": [],
                    "retry_queries": [],
                }
                for goal in planned_goals
            ],
        )
        return
    trace.record_coverage(
        attempt=attempt,
        status="sufficient" if assessment.sufficient else "insufficient",
        goal_results=[
            {
                "goal_id": result.goal_id,
                "description": result.description,
                "status": result.status,
                "evidence": [asdict(evidence) for evidence in result.evidence],
                "retry_queries": list(result.retry_queries),
            }
            for result in assessment.goals
        ],
    )


def _merge_retry_chunks(
    original: list[RetrievedChunk],
    supplemental: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """기존 청크를 먼저 보존하며 재검색 결과를 개수·문자 상한 안에서 합친다."""
    merged: list[RetrievedChunk] = []
    seen_ids: set[int] = set()
    used_chars = 0
    for chunk in [*original, *supplemental]:
        if chunk.chunk_id in seen_ids:
            continue
        if len(merged) >= MAX_RETRY_CONTEXT_CHUNKS:
            break
        if merged and used_chars + len(chunk.content) > MAX_RETRY_CONTEXT_CHARS:
            continue
        seen_ids.add(chunk.chunk_id)
        merged.append(chunk)
        used_chars += len(chunk.content)
    return merged
