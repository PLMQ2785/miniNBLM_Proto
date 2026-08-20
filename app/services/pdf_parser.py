from collections import Counter
from dataclasses import dataclass
import math
import re

import fitz


HEADER_FOOTER_BAND_RATIO = 0.12
REPEATED_MARGIN_MIN_RATIO = 0.3
BARE_PAGE_NUMBER_PATTERN = re.compile(
    r"^(?:page\s*)?\d+(?:\s*(?:/|of)\s*\d+)?$",
    re.IGNORECASE,
)
HANGUL_PATTERN = re.compile(r"[가-힣]")
LATIN_PATTERN = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    text: str
    metadata: dict


@dataclass(frozen=True)
class _TextBlock:
    y0: float
    y1: float
    text: str


@dataclass(frozen=True)
class _RawPage:
    page_number: int
    width: float
    height: float
    blocks: tuple[_TextBlock, ...]
    tables: tuple[_TextBlock, ...]
    image_count: int
    drawing_count: int


def extract_pages(pdf_path: str) -> list[ParsedPage]:
    with fitz.open(pdf_path) as document:
        raw_pages = [_extract_raw_page(page, index) for index, page in enumerate(document, 1)]
    # Repeated headers can only be identified after every page has been inspected.
    repeated_margin_lines = _repeated_margin_lines(raw_pages)
    pages: list[ParsedPage] = []
    for raw_page in raw_pages:
        content_blocks: list[_TextBlock] = []
        removed_lines: list[str] = []
        for block in raw_page.blocks:
            if _should_remove_margin_block(block, raw_page.height, repeated_margin_lines):
                removed_lines.append(block.text)
                continue
            content_blocks.append(block)

        content_blocks.extend(raw_page.tables)
        # Table rows rejoin the normal reading order by their vertical position.
        content_blocks.sort(key=lambda block: (block.y0, block.y1))
        text = "\n\n".join(block.text.strip() for block in content_blocks if block.text.strip())
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        text_chars = len(text)
        has_visual_content = raw_page.image_count > 0 or raw_page.drawing_count > 0
        visual_risk = _visual_evidence_risk(text_chars, has_visual_content)
        pages.append(
            ParsedPage(
                page_number=raw_page.page_number,
                text=text,
                metadata={
                    "width": raw_page.width,
                    "height": raw_page.height,
                    "text_chars": text_chars,
                    "image_count": raw_page.image_count,
                    "drawing_count": raw_page.drawing_count,
                    "table_count": len(raw_page.tables),
                    "removed_margin_lines": removed_lines,
                    "has_visual_content": has_visual_content,
                    "visual_evidence_risk": visual_risk,
                    "text_only_incomplete": visual_risk in {"empty_text", "visual_heavy"},
                    "language_hint": _language_hint(text),
                    "text_extraction_mode": "layout_blocks",
                },
            )
        )
    return pages


def _extract_raw_page(page: fitz.Page, page_number: int) -> _RawPage:
    page_dict = page.get_text("dict", sort=True)
    image_count = sum(1 for block in page_dict.get("blocks", []) if block.get("type") == 1)
    tables, table_rects = _extract_tables(page)
    text_blocks: list[_TextBlock] = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        bbox = fitz.Rect(block.get("bbox", (0, 0, 0, 0)))
        if any(_mostly_overlaps(bbox, table_rect) for table_rect in table_rects):
            continue
        lines: list[str] = []
        for line in block.get("lines", []):
            line_text = "".join(span.get("text", "") for span in line.get("spans", []))
            if line_text.strip():
                lines.append(line_text.strip())
        text = "\n".join(lines).strip()
        if text:
            text_blocks.append(_TextBlock(y0=bbox.y0, y1=bbox.y1, text=text))

    return _RawPage(
        page_number=page_number,
        width=float(page.rect.width),
        height=float(page.rect.height),
        blocks=tuple(text_blocks),
        tables=tuple(tables),
        image_count=image_count,
        drawing_count=len(page.get_drawings()),
    )


def _extract_tables(page: fitz.Page) -> tuple[list[_TextBlock], list[fitz.Rect]]:
    blocks: list[_TextBlock] = []
    table_rects: list[fitz.Rect] = []
    try:
        found_tables = page.find_tables().tables
    except Exception:
        return blocks, table_rects
    for table in found_tables:
        rows = table.extract()
        normalized_rows = [
            [" ".join(str(cell or "").split()) for cell in row]
            for row in rows
            if any(str(cell or "").strip() for cell in row)
        ]
        if not normalized_rows:
            continue
        table_text = "[Table]\n" + "\n".join(" | ".join(row) for row in normalized_rows)
        bbox = fitz.Rect(table.bbox)
        blocks.append(_TextBlock(y0=bbox.y0, y1=bbox.y1, text=table_text))
        table_rects.append(bbox)
    return blocks, table_rects


def _mostly_overlaps(block: fitz.Rect, table: fitz.Rect) -> bool:
    intersection = block & table
    if intersection.is_empty or block.get_area() <= 0:
        return False
    return intersection.get_area() / block.get_area() >= 0.6


def _repeated_margin_lines(raw_pages: list[_RawPage]) -> set[str]:
    if len(raw_pages) < 2:
        return set()
    counts: Counter[str] = Counter()
    for page in raw_pages:
        page_lines: set[str] = set()
        for block in page.blocks:
            if _is_margin_block(block, page.height):
                page_lines.update(
                    normalized
                    for line in block.text.splitlines()
                    if (normalized := _normalize_margin_line(line))
                )
        counts.update(page_lines)
    threshold = max(2, math.ceil(len(raw_pages) * REPEATED_MARGIN_MIN_RATIO))
    return {line for line, count in counts.items() if count >= threshold}


def _should_remove_margin_block(
    block: _TextBlock,
    page_height: float,
    repeated_margin_lines: set[str],
) -> bool:
    if not _is_margin_block(block, page_height):
        return False
    lines = [line.strip() for line in block.text.splitlines() if line.strip()]
    if lines and all(BARE_PAGE_NUMBER_PATTERN.fullmatch(line) for line in lines):
        return True
    normalized_lines = {_normalize_margin_line(line) for line in lines}
    normalized_lines.discard("")
    return bool(normalized_lines) and normalized_lines.issubset(repeated_margin_lines)


def _is_margin_block(block: _TextBlock, page_height: float) -> bool:
    return (
        block.y0 <= page_height * HEADER_FOOTER_BAND_RATIO
        or block.y1 >= page_height * (1 - HEADER_FOOTER_BAND_RATIO)
    )


def _normalize_margin_line(line: str) -> str:
    normalized = " ".join(line.casefold().split())
    if BARE_PAGE_NUMBER_PATTERN.fullmatch(normalized):
        return ""
    return normalized


def _visual_evidence_risk(text_chars: int, has_visual_content: bool) -> str:
    if text_chars < 20:
        return "empty_text" if has_visual_content else "empty"
    if has_visual_content and text_chars < 180:
        return "visual_heavy"
    if has_visual_content:
        return "mixed"
    return "text_only"


def _language_hint(text: str) -> str:
    hangul_count = len(HANGUL_PATTERN.findall(text))
    latin_count = len(LATIN_PATTERN.findall(text))
    if hangul_count and latin_count:
        dominant = max(hangul_count, latin_count)
        minority = min(hangul_count, latin_count)
        if minority / dominant >= 0.2:
            return "mixed"
    if hangul_count > latin_count:
        return "ko"
    if latin_count:
        return "en"
    return "unknown"
