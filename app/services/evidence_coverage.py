from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import time

from sqlalchemy.orm import Session

from app.clients.vllm_client import VLLMClient
from app.observability import (
    EVIDENCE_COVERAGE_DURATION,
    EVIDENCE_COVERAGE_REQUESTS,
    RETRIEVAL_RETRIES,
)
from app.services.hierarchical_retriever import retrieve_hierarchical_chunks
from app.services.retriever import RetrievedChunk, retrieve_chunks
from app.services.retrieval_trace import RetrievalTrace


logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "evidence_coverage_system_prompt.txt"
STATUS_PATTERN = re.compile(r"^STATUS\s*:\s*(SUFFICIENT|INSUFFICIENT)\s*$", re.IGNORECASE)
MISSING_PATTERN = re.compile(r"^MISSING\s*:\s*([0-9,\s]+)\s*$", re.IGNORECASE)
RETRY_PATTERN = re.compile(r"^RETRY\s+(\d+)\s*:\s*(.+?)\s*$", re.IGNORECASE)
MAX_COVERAGE_CONTEXT_CHARS = 18_000
MAX_RETRY_CONTEXT_CHARS = 18_000
MAX_RETRY_CONTEXT_CHUNKS = 20
JSON_OBJECT_RESPONSE_FORMAT = {"type": "json_object"}


@dataclass(frozen=True)
class EvidenceCoverageAssessment:
    sufficient: bool
    missing_queries: tuple[str, ...] = ()
    retry_queries: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceMatrix:
    status: str
    supported_goals: tuple[str, ...] = ()
    missing_goals: tuple[str, ...] = ()


def build_evidence_matrix(
    goals: tuple[str, ...],
    trace: RetrievalTrace | None,
) -> EvidenceMatrix:
    normalized_goals = tuple(dict.fromkeys(goal.strip() for goal in goals if goal.strip()))
    if not normalized_goals or trace is None:
        return EvidenceMatrix(status="unchecked")

    if trace.coverage_events and trace.coverage_events[-1].get("status") == "unchecked":
        return EvidenceMatrix(status="unchecked")

    decisive_event = next(
        (
            event
            for event in reversed(trace.coverage_events)
            if event.get("status") == "sufficient" or event.get("missing_queries")
        ),
        None,
    )
    if decisive_event is None:
        return EvidenceMatrix(status="unchecked")
    if decisive_event.get("status") == "sufficient":
        return EvidenceMatrix(status="complete", supported_goals=normalized_goals)

    missing_values = {
        str(query).strip().casefold()
        for query in decisive_event.get("missing_queries", [])
        if str(query).strip()
    }
    missing = tuple(goal for goal in normalized_goals if goal.casefold() in missing_values)
    supported = tuple(goal for goal in normalized_goals if goal.casefold() not in missing_values)
    if not missing:
        return EvidenceMatrix(status="unchecked")
    return EvidenceMatrix(
        status="partial" if supported else "insufficient",
        supported_goals=supported,
        missing_goals=missing,
    )


def complete_evidence_coverage(
    db: Session,
    owner_id: int,
    question: str,
    queries: tuple[str, ...],
    chunks: list[RetrievedChunk],
    trace: RetrievalTrace | None = None,
) -> list[RetrievedChunk]:
    if not chunks:
        return _recover_empty_initial_context(
            db=db,
            owner_id=owner_id,
            question=question,
            queries=queries,
            trace=trace,
        )

    coverage_queries = _coverage_queries(queries)
    assessment = assess_evidence_coverage(question, coverage_queries, chunks)
    if assessment is None:
        if trace is not None:
            trace.record_coverage(attempt=0, status="unchecked")
        return chunks
    if trace is not None:
        trace.record_coverage(
            attempt=0,
            status="sufficient" if assessment.sufficient else "insufficient",
            missing_queries=assessment.missing_queries,
            retry_queries=assessment.retry_queries,
        )
    if assessment.sufficient:
        return chunks

    targeted_chunks = retrieve_chunks(
        db=db,
        owner_id=owner_id,
        question=question,
        queries=assessment.retry_queries or assessment.missing_queries,
        trace=trace,
        trace_stage="targeted_retry_1",
    )
    if not targeted_chunks:
        RETRIEVAL_RETRIES.labels(status="empty_preserved").inc()
        merged_chunks = chunks
        next_assessment = assessment
    else:
        merged_chunks = _merge_retry_chunks(chunks, targeted_chunks)
        next_assessment = assess_evidence_coverage(question, coverage_queries, merged_chunks)
    if next_assessment is None:
        RETRIEVAL_RETRIES.labels(status="unchecked").inc()
        if trace is not None:
            trace.record_coverage(attempt=1, status="unchecked")
        return merged_chunks
    if next_assessment.sufficient:
        RETRIEVAL_RETRIES.labels(status="recovered").inc()
        if trace is not None:
            trace.record_coverage(attempt=1, status="sufficient")
        return merged_chunks
    if trace is not None:
        trace.record_coverage(
            attempt=1,
            status="insufficient_targeted_empty" if not targeted_chunks else "insufficient",
            missing_queries=next_assessment.missing_queries,
            retry_queries=next_assessment.retry_queries,
        )

    hierarchical_chunks = retrieve_hierarchical_chunks(
        db=db,
        owner_id=owner_id,
        question=question,
        queries=next_assessment.retry_queries or next_assessment.missing_queries or queries,
        trace=trace,
        trace_stage="hierarchical_retry_2",
    )
    if not hierarchical_chunks:
        RETRIEVAL_RETRIES.labels(status="hierarchical_empty_preserved").inc()
        if trace is not None:
            trace.record_coverage(attempt=2, status="empty_preserved")
        return merged_chunks

    final_chunks = _merge_retry_chunks(merged_chunks, hierarchical_chunks)
    final_assessment = assess_evidence_coverage(question, coverage_queries, final_chunks)
    if final_assessment is None:
        RETRIEVAL_RETRIES.labels(status="hierarchical_unchecked").inc()
        if trace is not None:
            trace.record_coverage(attempt=2, status="unchecked")
        return final_chunks
    status = "sufficient" if final_assessment.sufficient else "insufficient"
    RETRIEVAL_RETRIES.labels(
        status="hierarchical_recovered" if final_assessment.sufficient else "unresolved"
    ).inc()
    if trace is not None:
        trace.record_coverage(
            attempt=2,
            status=status,
            missing_queries=final_assessment.missing_queries,
            retry_queries=final_assessment.retry_queries,
        )
    return final_chunks


def _recover_empty_initial_context(
    *,
    db: Session,
    owner_id: int,
    question: str,
    queries: tuple[str, ...],
    trace: RetrievalTrace | None,
) -> list[RetrievedChunk]:
    if trace is not None:
        trace.record_coverage(attempt=0, status="no_initial_context")
    hierarchical_chunks = retrieve_hierarchical_chunks(
        db=db,
        owner_id=owner_id,
        question=question,
        queries=queries,
        trace=trace,
        trace_stage="hierarchical_retry_1",
    )
    if not hierarchical_chunks:
        RETRIEVAL_RETRIES.labels(status="hierarchical_empty").inc()
        if trace is not None:
            trace.record_coverage(attempt=1, status="empty")
        return []

    coverage_queries = _coverage_queries(queries)
    assessment = assess_evidence_coverage(question, coverage_queries, hierarchical_chunks)
    if assessment is None or assessment.sufficient:
        status = "unchecked" if assessment is None else "sufficient"
        RETRIEVAL_RETRIES.labels(status=f"hierarchical_{status}").inc()
        if trace is not None:
            trace.record_coverage(attempt=1, status=status)
        return hierarchical_chunks

    if trace is not None:
        trace.record_coverage(
            attempt=1,
            status="insufficient",
            missing_queries=assessment.missing_queries,
            retry_queries=assessment.retry_queries,
        )
    targeted_chunks = retrieve_chunks(
        db=db,
        owner_id=owner_id,
        question=question,
        queries=assessment.retry_queries or assessment.missing_queries,
        trace=trace,
        trace_stage="targeted_retry_2",
    )
    if not targeted_chunks:
        RETRIEVAL_RETRIES.labels(status="empty_preserved").inc()
        if trace is not None:
            trace.record_coverage(attempt=2, status="empty_preserved")
        return hierarchical_chunks

    merged_chunks = _merge_retry_chunks(hierarchical_chunks, targeted_chunks)
    final_assessment = assess_evidence_coverage(question, coverage_queries, merged_chunks)
    if trace is not None:
        trace.record_coverage(
            attempt=2,
            status=(
                "unchecked"
                if final_assessment is None
                else "sufficient" if final_assessment.sufficient else "insufficient"
            ),
            missing_queries=final_assessment.missing_queries if final_assessment else (),
            retry_queries=final_assessment.retry_queries if final_assessment else (),
        )
    RETRIEVAL_RETRIES.labels(
        status=(
            "unchecked"
            if final_assessment is None
            else "recovered" if final_assessment.sufficient else "unresolved"
        )
    ).inc()
    return merged_chunks


def assess_evidence_coverage(
    question: str,
    queries: tuple[str, ...],
    chunks: list[RetrievedChunk],
) -> EvidenceCoverageAssessment | None:
    if not queries or not chunks:
        return EvidenceCoverageAssessment(False, queries, queries)

    messages = [
        {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
        {
            "role": "user",
            "content": _build_coverage_request(question, queries, chunks),
        },
    ]
    started_at = time.perf_counter()
    try:
        response = VLLMClient().chat_completion(
            messages,
            temperature=0.0,
            operation="evidence_coverage",
            response_format=JSON_OBJECT_RESPONSE_FORMAT,
        )
        assessment = _parse_coverage_response(response, queries)
    except Exception:
        logger.warning("Evidence coverage check failed; using retrieved context", exc_info=True)
        EVIDENCE_COVERAGE_REQUESTS.labels(status="error").inc()
        return None
    else:
        status = "sufficient" if assessment.sufficient else "insufficient"
        EVIDENCE_COVERAGE_REQUESTS.labels(status=status).inc()
        return assessment
    finally:
        EVIDENCE_COVERAGE_DURATION.observe(time.perf_counter() - started_at)


def _coverage_queries(queries: tuple[str, ...]) -> tuple[str, ...]:
    return queries


def _build_coverage_request(
    question: str,
    queries: tuple[str, ...],
    chunks: list[RetrievedChunk],
) -> str:
    goals = "\n".join(f"{index}. {query}" for index, query in enumerate(queries, start=1))
    evidence_sections: list[str] = []
    used_chars = 0
    for index, chunk in enumerate(chunks, start=1):
        remaining_chars = MAX_COVERAGE_CONTEXT_CHARS - used_chars
        if remaining_chars <= 0:
            break
        content = chunk.content[:remaining_chars]
        evidence_sections.append(
            f"[Evidence {index}] {chunk.document_title} p.{chunk.page_start}\n{content}"
        )
        used_chars += len(content)
    evidence = "\n\n".join(evidence_sections)
    return (
        f"[Question]\n{question}\n\n"
        f"[Search goals]\n{goals}\n\n"
        f"[Evidence]\n{evidence}\n\n"
        "[Coverage result]"
    )


def _parse_coverage_response(
    response: str,
    queries: tuple[str, ...],
) -> EvidenceCoverageAssessment:
    if json_payload := _parse_coverage_json(response):
        status = str(json_payload.get("status", "")).upper()
        if status == "SUFFICIENT":
            return EvidenceCoverageAssessment(True)
        raw_missing = json_payload.get("missing", [])
        missing_indexes = [
            int(value)
            for value in raw_missing
            if str(value).isdigit() and 1 <= int(value) <= len(queries)
        ] if isinstance(raw_missing, list) else []
        raw_retries = json_payload.get("retry_queries", {})
        retry_by_index = {
            int(index): str(value).strip()
            for index, value in raw_retries.items()
            if str(index).isdigit() and str(value).strip()
        } if isinstance(raw_retries, dict) else {}
        if status == "INSUFFICIENT" and missing_indexes:
            return EvidenceCoverageAssessment(
                False,
                tuple(queries[index - 1] for index in missing_indexes),
                tuple(
                    retry_by_index.get(index, queries[index - 1])
                    for index in missing_indexes
                ),
            )

    lines = [_normalize_response_line(line) for line in response.splitlines()]
    lines = [line for line in lines if line]
    status = None
    missing_indexes: list[int] = []
    retry_by_index: dict[int, str] = {}
    for line in lines:
        if match := STATUS_PATTERN.match(line):
            status = match.group(1).upper()
        elif line.upper().startswith("STATUS:"):
            status_value = line.partition(":")[2].strip().upper()
            if "INSUFFICIENT" in status_value:
                status = "INSUFFICIENT"
            elif "SUFFICIENT" in status_value:
                status = "SUFFICIENT"
        elif match := MISSING_PATTERN.match(line):
            missing_indexes.extend(int(value) for value in match.group(1).split(","))
        elif match := RETRY_PATTERN.match(line):
            retry_by_index[int(match.group(1))] = match.group(2).strip()

    if status == "SUFFICIENT":
        return EvidenceCoverageAssessment(True)
    valid_indexes = list(
        dict.fromkeys(index for index in missing_indexes if 1 <= index <= len(queries))
    )
    if status != "INSUFFICIENT" or not valid_indexes:
        raise ValueError("Invalid evidence coverage response")
    missing_queries = tuple(queries[index - 1] for index in valid_indexes)
    retry_queries = tuple(
        retry_by_index.get(index, queries[index - 1]) for index in valid_indexes
    )
    return EvidenceCoverageAssessment(False, missing_queries, retry_queries)


def _parse_coverage_json(response: str) -> dict | None:
    candidate = response.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _normalize_response_line(line: str) -> str:
    normalized = line.strip()
    if normalized.startswith("```"):
        return ""
    normalized = re.sub(r"^[-*]\s+", "", normalized)
    return normalized.replace("**", "").replace("__", "").strip()


def _merge_retry_chunks(
    original: list[RetrievedChunk],
    supplemental: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    merged: list[RetrievedChunk] = []
    seen_ids: set[int] = set()
    used_chars = 0
    ordered_chunks = [*original, *supplemental]
    for chunk in ordered_chunks:
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
