from app.services.chunker import chunk_pages
from app.services.pdf_parser import ParsedPage


def test_chunk_preserves_page_quality_metadata() -> None:
    """텍스트 청크에도 원본 페이지의 시각 품질 메타데이터를 보존한다."""
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
    assert chunks[0].source_refs["page_metadata"]["has_visual_content"] is True
    assert chunks[0].metadata["visual_evidence_risk"] == "visual_heavy"
    assert chunks[0].content_type == "text"


def test_chunker_adds_separate_vision_caption_chunk() -> None:
    """완료된 Vision 설명은 텍스트와 분리된 검색 청크로 만든다."""
    page = ParsedPage(
        page_number=19,
        text="통신 화면 설명",
        metadata={
            "language_hint": "ko",
            "visual_evidence_risk": "visual_heavy",
            "vision_caption": {
                "status": "completed",
                "model": "gemma4",
                "version": "v1",
                "confidence": 0.95,
                "search_text": "[Vision evidence]\nVisible text:\n- LB05-01 NLNNN",
            },
        },
    )

    chunks = chunk_pages([page], document_id=12)

    assert [chunk.content_type for chunk in chunks] == ["text", "vision_caption"]
    assert chunks[1].source_refs["modality"] == "vision_caption"
    assert chunks[1].page_start == 19
    assert "LB05-01 NLNNN" in chunks[1].content
    assert "search_text" not in chunks[1].source_refs["page_metadata"]["vision_caption"]
