from pathlib import Path

import fitz

from app.evaluation.pdf_text_audit import audit_root
from app.evaluation.reasoning_benchmark import _automatic_gate
from app.evaluation.reasoning_fixture import load_reasoning_fixture


def test_sample_reasoning_fixture_covers_groups_and_expected_behaviors() -> None:
    fixture = load_reasoning_fixture(Path("evaluation/sample_multilayer_reasoning.json"))

    assert len(fixture.documents) == 19
    assert len(fixture.cases) == 10
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
    assert _automatic_gate("grounded_answer", "grounded") == "review"
    assert _automatic_gate("grounded_answer", "no_source") == "fail"
    assert _automatic_gate("qualified_answer", "grounded") == "review"
    assert _automatic_gate("qualified_answer", "no_source") == "fail"
    assert _automatic_gate("abstain", "no_source") == "pass"
    assert _automatic_gate("abstain", "grounded") == "fail"
