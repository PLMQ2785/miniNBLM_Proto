from dataclasses import dataclass

from app.services.pdf_parser import ParsedPage


@dataclass(frozen=True)
class TextChunk:
    content: str
    page_start: int | None
    page_end: int | None
    chunk_index: int
    source_refs: dict
    metadata: dict


def chunk_pages(
    pages: list[ParsedPage],
    chunk_size: int = 3500,
    chunk_overlap: int = 500,
    document_id: int | None = None,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    chunk_index = 0

    for page in pages:
        text = page.text.strip()
        if not text:
            continue

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
                        source_refs={
                            "document_id": document_id,
                            "pages": [page.page_number],
                        },
                        metadata={
                            "char_start": start,
                            "char_end": end,
                        },
                    )
                )
                chunk_index += 1

            if end >= len(text):
                break
            start = max(end - chunk_overlap, start + 1)

    return chunks
