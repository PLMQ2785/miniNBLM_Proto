from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.fixture import RetrievalEvaluationFixture, load_evaluation_fixture
from app.evaluation.metrics import (
    RankedReference,
    RetrievalScore,
    aggregate_scores,
    percentile,
    score_retrieval,
)
from app.evaluation.retrieval_benchmark import _quality_failures, render_markdown


def test_versioned_fixture_loads_and_references_known_document() -> None:
    fixture_path = Path("evaluation/retrieval_fall_prevention.json")
    fixture = load_evaluation_fixture(fixture_path)

    assert fixture.schema_version == 1
    assert len(fixture.documents) == 2
    assert len(fixture.cases) == 8
    assert all(
        (fixture_path.parent / document.path).resolve().is_file()
        for document in fixture.documents
    )
    assert {
        source.page
        for case in fixture.cases
        for source in case.relevant_sources
    } == {1, 2, 3, 4}


def test_fixture_rejects_unknown_relevant_document() -> None:
    with pytest.raises(ValidationError, match="unknown documents"):
        RetrievalEvaluationFixture.model_validate(
            {
                "schema_version": 1,
                "name": "invalid",
                "documents": [{"path": "lesson.pdf", "title": "lesson.pdf"}],
                "cases": [
                    {
                        "case_id": "unknown-source",
                        "question": "question",
                        "relevant_sources": [{"document": "missing.pdf", "page": 1}],
                    }
                ],
            }
        )


def test_retrieval_metrics_score_page_ranges_and_rank() -> None:
    score = score_retrieval(
        [
            RankedReference("lesson.pdf", 5, 5),
            RankedReference("lesson.pdf", 2, 3),
            RankedReference("lesson.pdf", 8, 8),
        ],
        relevant_sources={
            ("lesson.pdf", 2),
            ("lesson.pdf", 3),
            ("lesson.pdf", 8),
        },
        top_k=2,
    )

    assert score.recall_at_k == pytest.approx(2 / 3)
    assert score.hit_at_k == 1.0
    assert score.reciprocal_rank == 0.5
    assert score.first_relevant_rank == 2


def test_aggregate_scores_calculates_quality_and_latency_percentiles() -> None:
    metrics = aggregate_scores(
        [
            RetrievalScore(1.0, 1.0, 1.0, 1),
            RetrievalScore(0.0, 0.0, 0.0, None),
        ],
        [10.0, 20.0, 30.0],
    )

    assert metrics["recall_at_k"] == 0.5
    assert metrics["hit_rate_at_k"] == 0.5
    assert metrics["mrr_at_k"] == 0.5
    assert metrics["latency_mean_ms"] == 20.0
    assert metrics["latency_p50_ms"] == 20.0
    assert metrics["latency_p95_ms"] == 29.0
    assert metrics["latency_samples"] == 3
    assert percentile([7.0], 0.95) == 7.0


def test_markdown_report_and_recall_threshold_use_each_matrix_cell() -> None:
    report = {
        "fixture": {"name": "fixture", "case_count": 2},
        "run": {
            "completed_at": "2026-08-05T00:00:00+00:00",
            "iterations_per_case": 1,
            "evaluation_k": 5,
        },
        "presets": [
            {
                "preset": "balanced",
                "chunk_count": 4,
                "indexing_ms": 123.0,
                "algorithms": [
                    {
                        "algorithm": "dense",
                        "metrics": {
                            "recall_at_k": 0.75,
                            "hit_rate_at_k": 1.0,
                            "mrr_at_k": 0.5,
                            "latency_p50_ms": 12.0,
                            "latency_p95_ms": 20.0,
                        },
                    }
                ],
            }
        ],
    }

    markdown = render_markdown(report)

    assert "| balanced | dense | 4 | 0.750 |" in markdown
    assert _quality_failures(report, 0.75) == []
    assert _quality_failures(report, 0.80) == ["balanced/dense=0.750"]
