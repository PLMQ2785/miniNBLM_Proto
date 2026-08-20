import json

import pytest

from app.clients.llm_client import LLMClient
from app.services import evidence_coverage
from app.services.evidence_coverage import (
    EvidenceCoverageAssessment,
    GoalCoverage,
    assess_evidence_coverage,
    build_evidence_matrix,
    complete_evidence_coverage,
)
from app.services.query_rewriter import EvidenceGoal
from app.services.retrieval_trace import RetrievalTrace
from app.services.retriever import RetrievedChunk


def _chunk(
    chunk_id: int,
    content: str,
    page: int,
    document_title: str = "git.pdf",
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=10,
        document_title=document_title,
        content=content,
        page_start=page,
        page_end=page,
        score=0.9,
        source_refs={"page": page},
    )


def _goals() -> tuple[EvidenceGoal, ...]:
    return (
        EvidenceGoal("reset", "reset의 이력 변경 특성", ("git reset history",)),
        EvidenceGoal("revert", "revert의 공유 이력 안전성", ("git revert shared history",)),
    )


def _response(*goals: dict) -> str:
    return json.dumps({"goals": list(goals)}, ensure_ascii=False)


def test_coverage_maps_each_goal_to_verified_source_page_and_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: _response(
            {
                "goal_id": "reset",
                "status": "supported",
                "evidence_chunk_ids": [11],
                "retry_queries": [],
            },
            {
                "goal_id": "revert",
                "status": "partial",
                "evidence_chunk_ids": [12],
                "retry_queries": ["revert inverse commit collaboration"],
            },
        ),
    )

    assessment = assess_evidence_coverage(
        _goals(),
        [
            _chunk(11, "reset은 이력을 이동한다.", 3, "reset.pdf"),
            _chunk(12, "revert는 새 커밋을 만든다.", 8, "revert.pdf"),
        ],
    )

    assert assessment is not None
    assert assessment.sufficient is False
    assert assessment.goals[0].status == "supported"
    assert assessment.goals[0].evidence[0].document_title == "reset.pdf"
    assert assessment.goals[0].evidence[0].page_start == 3
    assert assessment.goals[1].evidence[0].chunk_id == 12
    assert assessment.goals[1].retry_queries == (
        "revert inverse commit collaboration",
    )


def test_unknown_chunk_id_is_repaired_once_and_json_mode_is_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    def assess(self, messages, **kwargs):
        calls.append(kwargs)
        chunk_id = 999 if len(calls) == 1 else 11
        return _response(
            {
                "goal_id": "reset",
                "status": "supported",
                "evidence_chunk_ids": [chunk_id],
                "retry_queries": [],
            },
            {
                "goal_id": "revert",
                "status": "missing",
                "evidence_chunk_ids": [],
                "retry_queries": ["git revert shared history"],
            },
        )

    monkeypatch.setattr(LLMClient, "chat_completion", assess)

    assessment = assess_evidence_coverage(_goals(), [_chunk(11, "reset evidence", 2)])

    assert assessment is not None
    assert len(calls) == 2
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[1]["operation"] == "evidence_coverage_repair"



# Guessing unknown IDs would attach a claim to the wrong source.
def test_failed_repair_uses_unchecked_matrix_instead_of_guessing_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    malformed = _response(
        {
            "goal_id": "goal_1",
            "status": "sufficient",
            "evidence_chunk_ids": ["11", 999],
            "retry_queries": [],
        },
        {
            "goal_id": "unknown",
            "status": "invalid",
            "evidence_chunk_ids": [999],
            "retry_queries": [],
        },
    )

    def assess(*args, **kwargs):
        nonlocal calls
        calls += 1
        return malformed

    monkeypatch.setattr(LLMClient, "chat_completion", assess)

    assessment = assess_evidence_coverage(
        _goals(),
        [_chunk(11, "reset evidence", 2)],
    )

    assert calls == 2
    assert assessment is None


def test_duplicate_or_omitted_goal_after_repair_returns_unchecked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = _response(
        {
            "goal_id": "reset",
            "status": "supported",
            "evidence_chunk_ids": [11],
            "retry_queries": [],
        }
    )
    monkeypatch.setattr(LLMClient, "chat_completion", lambda *args, **kwargs: invalid)

    assert assess_evidence_coverage(_goals(), [_chunk(11, "evidence", 2)]) is None


def test_targeted_retry_searches_only_unresolved_goal_and_merges_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessments = iter(
        [
            EvidenceCoverageAssessment(
                (
                    GoalCoverage("reset", "reset의 이력 변경 특성", "supported"),
                    GoalCoverage(
                        "revert",
                        "revert의 공유 이력 안전성",
                        "missing",
                        retry_queries=("revert inverse commit",),
                    ),
                )
            ),
            EvidenceCoverageAssessment(
                (
                    GoalCoverage("reset", "reset의 이력 변경 특성", "supported"),
                    GoalCoverage("revert", "revert의 공유 이력 안전성", "supported"),
                )
            ),
        ]
    )
    captured: list[tuple[EvidenceGoal, ...]] = []
    monkeypatch.setattr(
        evidence_coverage,
        "assess_evidence_coverage",
        lambda goals, chunks: next(assessments),
    )

    def retrieve(**kwargs):
        captured.append(kwargs["goals"])
        return [_chunk(12, "revert는 역커밋을 생성한다.", 8)]

    monkeypatch.setattr(evidence_coverage, "retrieve_chunks", retrieve)

    result = complete_evidence_coverage(
        db=object(),
        owner_id=1,
        question="왜 revert인가요?",
        goals=_goals(),
        chunks=[_chunk(11, "reset은 공유 이력을 변경한다.", 3)],
    )

    assert [chunk.chunk_id for chunk in result] == [11, 12]
    assert tuple(goal.goal_id for goal in captured[0]) == ("revert",)
    assert captured[0][0].queries == ("revert inverse commit",)


def test_unresolved_evidence_uses_exactly_two_bounded_retrieval_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unresolved = EvidenceCoverageAssessment(
        (
            GoalCoverage("reset", "reset의 이력 변경 특성", "supported"),
            GoalCoverage("revert", "revert의 공유 이력 안전성", "missing"),
        )
    )
    calls: list[int] = []
    monkeypatch.setattr(
        evidence_coverage,
        "assess_evidence_coverage",
        lambda goals, chunks: unresolved,
    )
    monkeypatch.setattr(
        evidence_coverage,
        "retrieve_chunks",
        lambda **kwargs: calls.append(1) or [],
    )

    result = complete_evidence_coverage(
        db=object(),
        owner_id=1,
        question="복합 질문",
        goals=_goals(),
        chunks=[_chunk(11, "partial", 1)],
    )

    assert [chunk.chunk_id for chunk in result] == [11]
    assert len(calls) == 2


def test_empty_initial_context_uses_hierarchical_fallback_before_targeted_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovered = [_chunk(21, "hierarchical evidence", 4)]
    monkeypatch.setattr(
        evidence_coverage,
        "retrieve_hierarchical_chunks",
        lambda **kwargs: recovered,
    )
    monkeypatch.setattr(
        evidence_coverage,
        "assess_evidence_coverage",
        lambda goals, chunks: EvidenceCoverageAssessment(
            tuple(
                GoalCoverage(goal.goal_id, goal.description, "supported")
                for goal in goals
            )
        ),
    )

    result = complete_evidence_coverage(
        db=object(),
        owner_id=1,
        question="복합 질문",
        goals=_goals(),
        chunks=[],
    )

    assert result == recovered


def test_empty_hierarchical_result_uses_remaining_targeted_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovered = [_chunk(22, "targeted evidence", 5)]
    monkeypatch.setattr(
        evidence_coverage,
        "retrieve_hierarchical_chunks",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        evidence_coverage,
        "retrieve_chunks",
        lambda **kwargs: recovered,
    )
    monkeypatch.setattr(
        evidence_coverage,
        "assess_evidence_coverage",
        lambda goals, chunks: (
            EvidenceCoverageAssessment(
                tuple(
                    GoalCoverage(goal.goal_id, goal.description, "supported")
                    for goal in goals
                )
            )
            if chunks
            else None
        ),
    )

    result = complete_evidence_coverage(
        db=object(),
        owner_id=1,
        question="복합 질문",
        goals=_goals(),
        chunks=[],
    )

    assert result == recovered


def test_evidence_matrix_preserves_goal_status_and_verified_references() -> None:
    trace = RetrievalTrace(request_id="req")
    trace.record_coverage(
        attempt=1,
        status="insufficient",
        goal_results=[
            {
                "goal_id": "reset",
                "description": "reset의 이력 변경 특성",
                "status": "supported",
                "evidence": [
                    {
                        "chunk_id": 11,
                        "document_title": "git.pdf",
                        "page_start": 3,
                        "page_end": 3,
                    }
                ],
                "retry_queries": [],
            },
            {
                "goal_id": "revert",
                "description": "revert의 공유 이력 안전성",
                "status": "contradicted",
                "evidence": [
                    {
                        "chunk_id": 12,
                        "document_title": "git.pdf",
                        "page_start": 8,
                        "page_end": 8,
                    }
                ],
                "retry_queries": ["revert collaboration"],
            },
        ],
    )

    matrix = build_evidence_matrix(_goals(), trace)

    assert matrix.status == "partial"
    assert tuple(goal.status for goal in matrix.goals) == ("supported", "contradicted")
    assert matrix.goals[0].evidence[0].chunk_id == 11


def test_unchecked_matrix_never_reuses_stale_goal_results() -> None:
    trace = RetrievalTrace(request_id="req")
    trace.record_coverage(
        attempt=0,
        status="sufficient",
        goal_results=[
            {
                "goal_id": goal.goal_id,
                "description": goal.description,
                "status": "supported",
                "evidence": [],
                "retry_queries": [],
            }
            for goal in _goals()
        ],
    )
    trace.record_coverage(
        attempt=1,
        status="unchecked",
        goal_results=[
            {
                "goal_id": goal.goal_id,
                "description": goal.description,
                "status": "unchecked",
                "evidence": [],
                "retry_queries": [],
            }
            for goal in _goals()
        ],
    )

    matrix = build_evidence_matrix(_goals(), trace)

    assert matrix.status == "unchecked"
    assert all(goal.status == "unchecked" for goal in matrix.goals)
