from dataclasses import dataclass, field
from datetime import UTC, datetime
import time
from typing import Any

from app.services.query_rewriter import EvidenceGoal


MAX_TRACE_CANDIDATES = 20


@dataclass
class RetrievalTrace:
    """검색 계획부터 최종 인용까지 채팅 행에 남길 진단 정보를 모은다."""
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
        goals: tuple[EvidenceGoal, ...],
    ) -> None:
        """독립 질문과 근거 목표를 실제 검색 계획 형태로 기록한다."""
        queries = list(
            dict.fromkeys(
                [
                    standalone_query,
                    *(query for goal in goals for query in goal.queries),
                ]
            )
        )
        self.query_plan = {
            "standalone_query": standalone_query,
            "queries": queries,
            "evidence_goals": [
                {
                    "goal_id": goal.goal_id,
                    "description": goal.description,
                    "queries": list(goal.queries),
                }
                for goal in goals
            ],
        }

    def record_candidates(
        self,
        *,
        stage: str,
        query: str | None,
        algorithm: str,
        rows,
        goal_ids: tuple[str | None, ...] = (),
    ) -> None:
        """검색 단계의 후보 스냅샷을 제한된 크기로 기록한다."""
        # 진단 메타데이터가 채팅 행을 키우지 않도록 후보 수를 제한한다.
        self.retrieval_events.append(
            {
                "stage": stage,
                "query": query,
                "algorithm": algorithm,
                "result_count": len(rows),
                "candidates": [_candidate_snapshot(row) for row in rows[:MAX_TRACE_CANDIDATES]],
                "goal_ids": list(dict.fromkeys(goal_id for goal_id in goal_ids if goal_id)),
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
        """검색 완료 결과와 소요 시간을 단계별로 기록한다."""
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
        """실패한 검색 단계와 실패 전 소요 시간을 기록한다."""
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
        goal_results: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    ) -> None:
        """근거 충족도 판정과 목표별 결과를 시도 순서대로 기록한다."""
        self.coverage_events.append(
            {
                "attempt": attempt,
                "status": status,
                "goals": [dict(result) for result in goal_results],
            }
        )

    def record_pages(self, *, stage: str, pages) -> None:
        """계층 검색이 찾은 페이지 후보를 제한된 크기로 기록한다."""
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
        """최종 답변의 근거·인용 상태를 확정하고 직렬화한다."""
        # 프롬프트에 쓴 청크와 실제 인용한 청크를 의도적으로 따로 남긴다.
        self.outcome = {
            "status": _answer_status(answer, chunks, sources),
            "final_chunk_ids": [chunk.chunk_id for chunk in chunks],
            "final_modalities": [chunk.content_type for chunk in chunks],
            "cited_chunk_ids": [source.chunk_id for source in sources],
            "duration_ms": round((time.perf_counter() - self.started_at) * 1000, 2),
        }
        return self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        """저장 가능한 추적 메타데이터 사전으로 변환한다."""
        return {
            "schema_version": 4,
            "request_id": self.request_id,
            "created_at": self.created_at,
            "query_plan": self.query_plan,
            "retrieval_events": self.retrieval_events,
            "coverage_events": self.coverage_events,
            "outcome": self.outcome,
        }


def _candidate_snapshot(row) -> dict[str, Any]:
    """저장 크기를 줄인 검색 후보 요약을 만든다."""
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
    """최종 답변을 인용·컨텍스트 유무에 따라 분류한다."""
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
