from pathlib import Path

import fitz
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


def test_multihop_fixture_defines_evidence_facets_and_existing_pdf_pages() -> None:
    fixture_path = Path("evaluation/retrieval_multihop_oss.json")
    fixture = load_evaluation_fixture(fixture_path)

    assert fixture.schema_version == 2
    assert len(fixture.documents) == 2
    assert len(fixture.cases) == 7
    assert all(1 <= len(case.retrieval_queries) <= 4 for case in fixture.cases)
    assert all(case.evidence_facets for case in fixture.cases)
    assert all(case.required_answer_claims for case in fixture.cases)
    assert len(fixture.cases[0].evidence_facets) == 3
    assert len(fixture.cases[1].evidence_facets) == 3
    assert {
        "ignored-secret-stash-indirect",
        "pushed-revert-dvcs-indirect",
    }.issubset({case.case_id for case in fixture.cases})

    page_counts = {}
    for document in fixture.documents:
        path = (fixture_path.parent / document.path).resolve()
        assert path.is_file()
        with fitz.open(path) as pdf:
            page_counts[document.title] = pdf.page_count
            assert all(page.get_text().strip() for page in pdf)

    assert all(
        source.page <= page_counts[source.document]
        for case in fixture.cases
        for source in case.relevant_sources
    )


def test_work_education_fixture_covers_domains_languages_and_pdf_pages() -> None:
    fixture_path = Path("evaluation/retrieval_work_education.json")
    fixture = load_evaluation_fixture(fixture_path)

    assert fixture.schema_version == 2
    assert len(fixture.documents) == 5
    assert len(fixture.cases) == 24
    assert all(case.retrieval_queries for case in fixture.cases)
    assert all(case.evidence_facets for case in fixture.cases)
    assert all(case.required_answer_claims for case in fixture.cases)
    assert any(case.question.isascii() for case in fixture.cases)
    assert any(len(case.relevant_sources) >= 3 for case in fixture.cases)

    page_counts = {}
    for document in fixture.documents:
        path = fixture_path.parent / document.path
        with fitz.open(path) as pdf:
            page_counts[document.title] = pdf.page_count
            assert pdf.page_count == (
                8 if document.title == "retrieval_work_hard_negatives.pdf" else 4
            )
            assert all(len(page.get_text().strip()) >= 100 for page in pdf)
    assert {
        case.case_id for case in fixture.cases if case.case_id.startswith("hard-negative-")
    } == {
        "hard-negative-sev1-vs-sev2",
        "hard-negative-production-recovery",
        "hard-negative-restricted-link",
        "hard-negative-original-recording",
    }

    assert all(
        source.page <= page_counts[source.document]
        for case in fixture.cases
        for source in case.relevant_sources
    )


def test_schema_v2_requires_queries_facets_and_answer_claims() -> None:
    with pytest.raises(ValidationError, match="require retrieval queries, evidence facets"):
        RetrievalEvaluationFixture.model_validate(
            {
                "schema_version": 2,
                "name": "incomplete-v2",
                "documents": [{"path": "lesson.pdf", "title": "lesson.pdf"}],
                "cases": [
                    {
                        "case_id": "missing-contract",
                        "question": "question",
                        "relevant_sources": [{"document": "lesson.pdf", "page": 1}],
                    }
                ],
            }
        )


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
            "reranker": "cross_encoder",
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
    assert "- Reranker: `cross_encoder`" in markdown

    assert "| balanced | dense | 4 | 0.750 |" in markdown
    assert _quality_failures(report, 0.75) == []
    assert _quality_failures(report, 0.80) == ["balanced/dense=0.750"]
