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
    """청킹과 시각 보강에 전달할 페이지 텍스트와 출처 메타데이터다."""
    page_number: int
    text: str
    metadata: dict


@dataclass(frozen=True)
class _TextBlock:
    """페이지 읽기 순서를 보존하기 위한 위치 기반 텍스트 조각이다."""
    y0: float
    y1: float
    text: str


@dataclass(frozen=True)
class _RawPage:
    """전 페이지 비교 전에 보관하는 원시 레이아웃과 시각 요소 통계다."""
    page_number: int
    width: float
    height: float
    blocks: tuple[_TextBlock, ...]
    tables: tuple[_TextBlock, ...]
    image_count: int
    drawing_count: int


def extract_pages(pdf_path: str) -> list[ParsedPage]:
    """PDF 레이아웃을 읽고 반복 여백을 제거한 출처 보존 페이지를 만든다."""
    with fitz.open(pdf_path) as document:
        raw_pages = [_extract_raw_page(page, index) for index, page in enumerate(document, 1)]
    # 반복 머리말과 꼬리말은 모든 페이지를 본 뒤에만 판별할 수 있다.
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
        # 표도 세로 위치에 따라 본문 읽기 순서에 다시 합친다.
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
    """한 페이지에서 표와 중복되지 않는 본문 블록 및 시각 통계를 추출한다."""
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
    """표 셀을 검색 가능한 행 텍스트로 바꾸고 원래 영역을 함께 반환한다."""
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
    """본문 블록이 표 영역과 충분히 겹쳐 중복 추출됐는지 판별한다."""
    intersection = block & table
    if intersection.is_empty or block.get_area() <= 0:
        return False
    return intersection.get_area() / block.get_area() >= 0.6


def _repeated_margin_lines(raw_pages: list[_RawPage]) -> set[str]:
    """여러 페이지 여백에 반복되는 문구를 머리말·꼬리말 후보로 모은다."""
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
    """페이지 번호나 반복 여백만 담은 블록을 본문에서 제외할지 판별한다."""
    if not _is_margin_block(block, page_height):
        return False
    lines = [line.strip() for line in block.text.splitlines() if line.strip()]
    if lines and all(BARE_PAGE_NUMBER_PATTERN.fullmatch(line) for line in lines):
        return True
    normalized_lines = {_normalize_margin_line(line) for line in lines}
    normalized_lines.discard("")
    return bool(normalized_lines) and normalized_lines.issubset(repeated_margin_lines)


def _is_margin_block(block: _TextBlock, page_height: float) -> bool:
    """텍스트 블록이 페이지 상하단 여백 띠에 있는지 확인한다."""
    return (
        block.y0 <= page_height * HEADER_FOOTER_BAND_RATIO
        or block.y1 >= page_height * (1 - HEADER_FOOTER_BAND_RATIO)
    )


def _normalize_margin_line(line: str) -> str:
    """여백 문구 비교를 위해 공백과 대소문자를 통일하고 페이지 번호를 버린다."""
    normalized = " ".join(line.casefold().split())
    if BARE_PAGE_NUMBER_PATTERN.fullmatch(normalized):
        return ""
    return normalized


def _visual_evidence_risk(text_chars: int, has_visual_content: bool) -> str:
    """텍스트 양과 시각 요소를 조합해 캡션 보강 필요도를 분류한다."""
    if text_chars < 20:
        return "empty_text" if has_visual_content else "empty"
    if has_visual_content and text_chars < 180:
        return "visual_heavy"
    if has_visual_content:
        return "mixed"
    return "text_only"


def _language_hint(text: str) -> str:
    """추출 텍스트의 한글·라틴 문자 비율로 페이지 언어 힌트를 만든다."""
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
