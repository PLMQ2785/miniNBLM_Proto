from dataclasses import dataclass

from app.services.pdf_parser import ParsedPage


@dataclass(frozen=True)
class TextChunk:
    """검색 결과가 텍스트·시각 출처로 돌아갈 수 있게 근거 위치를 담는다."""
    content: str
    page_start: int | None
    page_end: int | None
    chunk_index: int
    content_type: str
    source_refs: dict
    metadata: dict


def chunk_pages(
    pages: list[ParsedPage],
    chunk_size: int = 3500,
    chunk_overlap: int = 500,
    document_id: int | None = None,
) -> list[TextChunk]:
    """페이지 텍스트와 시각 캡션을 출처별 검색 청크로 나눈다."""
    chunks: list[TextChunk] = []
    chunk_index = 0

    for page in pages:
        text = page.text.strip()
        source_page_metadata = _source_page_metadata(page.metadata)
        if text:
            # 경계 문장도 양쪽 청크에서 검색되도록 일부 텍스트를 겹친다.
            start = 0
            while start < len(text):
                end = min(start + chunk_size, len(text))
                content = text[start:end].strip()
                if content:
                    chunks.append(
                        TextChunk(
                            content=content,
                            page_start=page.page_number,
                            page_end=page.page_number,
                            chunk_index=chunk_index,
                            content_type="text",
                            source_refs={
                                "document_id": document_id,
                                "pages": [page.page_number],
                                "modality": "text",
                                "page_metadata": source_page_metadata,
                            },
                            metadata={
                                "char_start": start,
                                "char_end": end,
                                "modality": "text",
                                "language_hint": page.metadata.get(
                                    "language_hint", "unknown"
                                ),
                                "visual_evidence_risk": page.metadata.get(
                                    "visual_evidence_risk", "unknown"
                                ),
                            },
                        )
                    )
                    chunk_index += 1

                if end >= len(text):
                    break
                start = max(end - chunk_overlap, start + 1)

        # 텍스트와 시각 근거의 출처를 구분하려고 캡션을 별도 청크로 둔다.
        vision = page.metadata.get("vision_caption", {})
        if isinstance(vision, dict) and vision.get("status") == "completed":
            content = str(vision.get("search_text", "")).strip()
            if content:
                chunks.append(
                    TextChunk(
                        content=content,
                        page_start=page.page_number,
                        page_end=page.page_number,
                        chunk_index=chunk_index,
                        content_type="vision_caption",
                        source_refs={
                            "document_id": document_id,
                            "pages": [page.page_number],
                            "modality": "vision_caption",
                            "page_metadata": source_page_metadata,
                        },
                        metadata={
                            "modality": "vision_caption",
                            "vision_model": vision.get("model"),
                            "vision_caption_version": vision.get("version"),
                            "vision_confidence": vision.get("confidence"),
                            "language_hint": page.metadata.get("language_hint", "unknown"),
                            "visual_evidence_risk": page.metadata.get(
                                "visual_evidence_risk", "unknown"
                            ),
                        },
                    )
                )
                chunk_index += 1

    return chunks


def _source_page_metadata(metadata: dict) -> dict:
    """청크 출처에 필요한 페이지·시각 보강 메타데이터만 추린다."""
    keys = (
        "width",
        "height",
        "text_chars",
        "image_count",
        "drawing_count",
        "table_count",
        "has_visual_content",
        "visual_evidence_risk",
        "text_only_incomplete",
        "language_hint",
        "text_extraction_mode",
    )
    compact = {key: metadata[key] for key in keys if key in metadata}
    vision = metadata.get("vision_caption")
    if isinstance(vision, dict):
        compact["vision_caption"] = {
            key: vision[key]
            for key in (
                "status",
                "version",
                "model",
                "confidence",
                "repaired",
                "error_type",
            )
            if key in vision
        }
    return compact
