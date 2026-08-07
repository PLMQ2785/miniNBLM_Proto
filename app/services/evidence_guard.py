from dataclasses import dataclass
import re

from app.services.retriever import RetrievedChunk


PAGE_PATTERNS = (
    re.compile(r"(?<!\d)(\d{1,4})\s*페이지"),
    re.compile(r"\bpage\s+(\d{1,4})\b", re.IGNORECASE),
    re.compile(r"\bp\.?\s*(\d{1,4})\b", re.IGNORECASE),
)
VISUAL_TERM_PATTERN = re.compile(
    r"스크린샷|화면|그림|도표|다이어그램|그래프|사진|이미지|표\b|"
    r"screenshot|figure|diagram|graph|image|table",
    re.IGNORECASE,
)
EXACT_VISUAL_TASK_PATTERN = re.compile(
    r"정확히|그대로|옮기|전사|표시된|계산|최종\s*(?:값|결과)|각\s*단계|"
    r"exact|transcrib|calculate|final\s+value|step[- ]by[- ]step",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EvidenceGuardDecision:
    answerable: bool
    reason: str | None = None
    pages: tuple[int, ...] = ()


def assess_text_only_answerability(
    question: str,
    chunks: list[RetrievedChunk],
) -> EvidenceGuardDecision:
    if not VISUAL_TERM_PATTERN.search(question) or not EXACT_VISUAL_TASK_PATTERN.search(question):
        return EvidenceGuardDecision(True)

    requested_pages = _requested_pages(question)
    candidates = [
        chunk
        for chunk in chunks
        if not requested_pages or _chunk_pages(chunk).intersection(requested_pages)
    ]
    if requested_pages and not candidates:
        return EvidenceGuardDecision(
            False,
            reason="requested_visual_page_is_missing_from_text_context",
            pages=tuple(sorted(requested_pages)),
        )
    risky_pages = sorted(
        {
            page
            for chunk in candidates
            if _has_unparsed_visual_content(chunk)
            for page in _chunk_pages(chunk)
            if not requested_pages or page in requested_pages
        }
    )
    if requested_pages and risky_pages:
        return EvidenceGuardDecision(
            False,
            reason="requested_visual_page_is_not_fully_represented_as_text",
            pages=tuple(risky_pages),
        )
    if not requested_pages and candidates and all(
        _visual_risk(chunk) in {"empty_text", "visual_heavy"} for chunk in candidates[:5]
    ):
        return EvidenceGuardDecision(
            False,
            reason="retrieved_evidence_is_visual_heavy",
            pages=tuple(risky_pages),
        )
    return EvidenceGuardDecision(True)


def _requested_pages(question: str) -> set[int]:
    return {
        int(match.group(1))
        for pattern in PAGE_PATTERNS
        for match in pattern.finditer(question)
    }


def _chunk_pages(chunk: RetrievedChunk) -> set[int]:
    if chunk.page_start is None:
        return set()
    end = chunk.page_end if chunk.page_end is not None else chunk.page_start
    return set(range(chunk.page_start, end + 1))


def _page_metadata(chunk: RetrievedChunk) -> dict:
    metadata = chunk.source_refs.get("page_metadata", {})
    return metadata if isinstance(metadata, dict) else {}


def _visual_risk(chunk: RetrievedChunk) -> str:
    return str(_page_metadata(chunk).get("visual_evidence_risk", "unknown"))


def _has_unparsed_visual_content(chunk: RetrievedChunk) -> bool:
    metadata = _page_metadata(chunk)
    return bool(metadata.get("has_visual_content")) or _visual_risk(chunk) in {
        "empty_text",
        "visual_heavy",
        "mixed",
    }
