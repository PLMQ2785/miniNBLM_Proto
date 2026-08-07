from dataclasses import dataclass, field
from datetime import UTC, datetime
import time
from typing import Any


MAX_TRACE_CANDIDATES = 20


@dataclass
class RetrievalTrace:
    request_id: str
    started_at: float = field(default_factory=time.perf_counter)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    query_plan: dict[str, Any] = field(default_factory=dict)
    retrieval_events: list[dict[str, Any]] = field(default_factory=list)
    coverage_events: list[dict[str, Any]] = field(default_factory=list)
    outcome: dict[str, Any] = field(default_factory=dict)

    def set_query_plan(
        self,
        standalone_query: str,
        queries: tuple[str, ...],
        evidence_goals: tuple[str, ...] = (),
    ) -> None:
        self.query_plan = {
            "standalone_query": standalone_query,
            "queries": list(queries),
            "evidence_goals": list(evidence_goals),
        }

    def record_candidates(
        self,
        *,
        stage: str,
        query: str | None,
        algorithm: str,
        rows,
    ) -> None:
        self.retrieval_events.append(
            {
                "stage": stage,
                "query": query,
                "algorithm": algorithm,
                "result_count": len(rows),
                "candidates": [_candidate_snapshot(row) for row in rows[:MAX_TRACE_CANDIDATES]],
            }
        )

    def record_retrieval_complete(
        self,
        *,
        stage: str,
        algorithm: str,
        queries: list[str],
        rows,
        duration_seconds: float,
    ) -> None:
        self.retrieval_events.append(
            {
                "stage": f"{stage}.complete",
                "algorithm": algorithm,
                "queries": queries,
                "result_count": len(rows),
                "duration_ms": round(duration_seconds * 1000, 2),
                "candidates": [_candidate_snapshot(row) for row in rows[:MAX_TRACE_CANDIDATES]],
            }
        )

    def record_retrieval_error(
        self,
        *,
        stage: str,
        algorithm: str,
        duration_seconds: float,
    ) -> None:
        self.retrieval_events.append(
            {
                "stage": f"{stage}.error",
                "algorithm": algorithm,
                "duration_ms": round(duration_seconds * 1000, 2),
            }
        )

    def record_coverage(
        self,
        *,
        attempt: int,
        status: str,
        missing_queries: tuple[str, ...] = (),
        retry_queries: tuple[str, ...] = (),
    ) -> None:
        self.coverage_events.append(
            {
                "attempt": attempt,
                "status": status,
                "missing_queries": list(missing_queries),
                "retry_queries": list(retry_queries),
            }
        )

    def record_pages(self, *, stage: str, pages) -> None:
        self.retrieval_events.append(
            {
                "stage": stage,
                "result_count": len(pages),
                "pages": [
                    {
                        "document_id": page.document_id,
                        "document_title": title,
                        "page": page.page_number,
                        "score": round(float(score), 6),
                    }
                    for page, score, title in pages[:MAX_TRACE_CANDIDATES]
                ],
            }
        )

    def complete(self, *, answer: str, chunks, sources) -> dict[str, Any]:
        self.outcome = {
            "status": _answer_status(answer, chunks, sources),
            "final_chunk_ids": [chunk.chunk_id for chunk in chunks],
            "final_modalities": [chunk.content_type for chunk in chunks],
            "cited_chunk_ids": [source.chunk_id for source in sources],
            "duration_ms": round((time.perf_counter() - self.started_at) * 1000, 2),
        }
        return self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 3,
            "request_id": self.request_id,
            "created_at": self.created_at,
            "query_plan": self.query_plan,
            "retrieval_events": self.retrieval_events,
            "coverage_events": self.coverage_events,
            "outcome": self.outcome,
        }


def _candidate_snapshot(row) -> dict[str, Any]:
    if hasattr(row, "chunk_id") and hasattr(row, "document_title"):
        chunk = row
        score = getattr(row, "score", 0.0)
        document_title = getattr(row, "document_title", "")
    else:
        chunk, score, document_title = row
    return {
        "chunk_id": chunk.id if hasattr(chunk, "id") else chunk.chunk_id,
        "document_id": chunk.document_id,
        "document_title": document_title,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "content_type": getattr(chunk, "content_type", "text"),
        "score": round(float(score), 6),
    }


def _answer_status(answer: str, chunks, sources) -> str:
    if sources:
        return "grounded"
    if not chunks:
        return "no_context"
    if answer.strip().startswith(
        (
            "업로드된 자료에서 확인되지 않습니다",
            "업로드된 자료에서 관련 내용을 찾지 못했습니다",
        )
    ):
        return "no_source"
    return "uncited_answer"
