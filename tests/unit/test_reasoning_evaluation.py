from pathlib import Path

import fitz

from app.evaluation.pdf_text_audit import audit_root
from app.evaluation.reasoning_benchmark import _automatic_gate, _citation_metrics, _failure_reason
from app.evaluation.reasoning_fixture import ReasoningCase, load_reasoning_fixture
from app.services.generator import INSUFFICIENT_EVIDENCE_ANSWER


def test_sample_reasoning_fixture_covers_groups_and_expected_behaviors() -> None:
    """샘플 추론 fixture가 그룹·응답 유형·시각 근거 범위를 갖춘다."""
    fixture = load_reasoning_fixture(Path("evaluation/sample_multilayer_reasoning.json"))

    assert len(fixture.documents) == 19
    assert len(fixture.cases) == 11
    assert {case.group for case in fixture.cases} == {
        "Manual",
        "OpenSWDesign",
        "OpenSWUnderstand",
    }
    assert {case.expected_behavior for case in fixture.cases} == {
        "grounded_answer",
        "qualified_answer",
        "abstain",
    }
    assert {case.evidence_modality for case in fixture.cases} >= {
        "text",
        "visual_only",
    }
    assert all(1 <= len(case.reference_queries) <= 4 for case in fixture.cases)


def test_pdf_text_audit_marks_empty_and_visual_heavy_pages(tmp_path: Path) -> None:
    """PDF 감사는 빈 페이지와 도형 중심 페이지를 서로 구분한다."""
    group_dir = tmp_path / "group"
    group_dir.mkdir()
    pdf_path = group_dir / "audit.pdf"
    with fitz.open() as document:
        document.new_page()
        visual_page = document.new_page()
        visual_page.insert_text((40, 40), "short")
        for offset in range(10):
            visual_page.draw_rect(fitz.Rect(20 + offset, 20, 200 + offset, 200))
        document.save(pdf_path)

    report = audit_root(tmp_path)

    assert report["document_count"] == 1
    assert report["page_count"] == 2
    pages = report["documents"][0]["pages"]
    assert pages[0]["risk"] == "empty_text"
    assert pages[1]["risk"] == "visual_heavy"


def test_reasoning_automatic_gate_requires_grounding_or_abstention() -> None:
    """자동 판정은 근거 있는 답변이나 올바른 답변 보류만 통과시킨다."""
    assert _automatic_gate("grounded_answer", "grounded") == "review"
    assert _automatic_gate("grounded_answer", "no_source") == "fail"
    assert _automatic_gate("qualified_answer", "grounded") == "review"
    assert _automatic_gate("qualified_answer", "no_source") == "fail"
    assert _automatic_gate("abstain", "no_source") == "pass"
    assert _automatic_gate("abstain", "grounded") == "fail"
    assert (
        _automatic_gate("abstain", "uncited_answer", INSUFFICIENT_EVIDENCE_ANSWER)
        == "pass"
    )


def test_reasoning_metrics_detect_retrieval_and_source_interference() -> None:
    """추론 지표는 검색 누락과 예상 밖 출처 혼입을 구분한다."""
    case = ReasoningCase.model_validate(
        {
            "case_id": "metric-case",
            "group": "group",
            "question": "question",
            "reasoning_depth": 1,
            "answerability": "full",
            "expected_behavior": "grounded_answer",
            "evidence_modality": "text",
            "reference_queries": ["query"],
            "relevant_sources": [{"document": "expected.pdf", "page": 3}],
            "evidence_facets": [
                {
                    "facet_id": "fact",
                    "description": "fact",
                    "relevant_sources": [{"document": "expected.pdf", "page": 3}],
                }
            ],
            "required_answer_claims": ["expected claim"],
        }
    )

    class Source:
        """인용 지표가 읽는 문서 제목과 페이지만 제공한다."""
        def __init__(self, document_title: str, page: int) -> None:
            """인용 출처의 문서 제목과 페이지를 보관한다."""
            self.document_title = document_title
            self.page = page

    citation = _citation_metrics(
        case,
        [Source("expected.pdf", 3), Source("distractor.pdf", 9)],
    )

    assert citation["status"] == "review"
    assert citation["expected_source_precision"] == 0.5
    assert citation["unexpected_sources"] == [{"document": "distractor.pdf", "page": 9}]
    assert _failure_reason(
        case,
        final_source_recall=1.0,
        outcome_status="grounded",
        citation_accuracy=citation,
    ) is None
    assert _failure_reason(
        case,
        final_source_recall=0.0,
        outcome_status="grounded",
        citation_accuracy=citation,
    ) == "retrieval_gap"
