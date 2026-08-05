from dataclasses import dataclass

import fitz


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    text: str
    metadata: dict


def extract_pages(pdf_path: str) -> list[ParsedPage]:
    pages: list[ParsedPage] = []
    with fitz.open(pdf_path) as document:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            pages.append(
                ParsedPage(
                    page_number=index,
                    text=text,
                    metadata={
                        "width": page.rect.width,
                        "height": page.rect.height,
                    },
                )
            )
    return pages
