from app.services.chunker import chunk_pages
from app.services.pdf_parser import ParsedPage


def test_chunk_preserves_page_quality_metadata() -> None:
    page = ParsedPage(
        page_number=7,
        text="다이어그램 설명",
        metadata={
            "language_hint": "ko",
            "visual_evidence_risk": "visual_heavy",
            "has_visual_content": True,
        },
    )

    chunks = chunk_pages([page], document_id=12)

    assert len(chunks) == 1
    assert chunks[0].source_refs["page_metadata"] == page.metadata
    assert chunks[0].metadata["visual_evidence_risk"] == "visual_heavy"
