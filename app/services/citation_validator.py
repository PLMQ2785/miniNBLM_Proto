import logging
from pathlib import Path
import re
import time

from app.clients.llm_client import LLMClient
from app.observability import CITATION_VALIDATION_DURATION, CITATION_VALIDATION_REQUESTS
from app.services.prompt_builder import build_retrieval_context
from app.services.retriever import RetrievedChunk


logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "citation_repair_system_prompt.txt"
MAX_VALIDATION_CONTEXT_CHARS = 18_000
NO_SOURCE_PATTERN = re.compile(r"^\s*\[{1,2}\s*NO_SOURCE\b", re.IGNORECASE)
CITATION_ITEM_PATTERN = re.compile(
    r"Source\s+(?P<source>\d+)\s*,\s*Page\s+(?P<start>\d+)"
    r"(?:\s*-\s*(?P<end>\d+))?",
    re.IGNORECASE,
)
CITATION_GROUP_PATTERN = re.compile(
    r"\[(?P<body>(?=[^\]]*\bSource\s+\d+\b)[^\]]+)\]",
    re.IGNORECASE,
)
SOURCE_TOKEN_PATTERN = re.compile(r"\bSource\s+\d+\b", re.IGNORECASE)
BARE_SOURCE_PATTERN = re.compile(
    r"\bSource\s+(?P<source>\d+)\b(?!\s*,\s*Page\b)",
    re.IGNORECASE,
)
CHUNK_SUFFIX_PATTERN = re.compile(r"\s*,\s*Chunk\s+\d+\b", re.IGNORECASE)
MARKDOWN_PREFIX_PATTERN = re.compile(r"^(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)")
WORD_PATTERN = re.compile(r"[0-9A-Za-z가-힣]")
CLAIM_SEGMENT_PATTERN = re.compile(
    r".+?(?:[.!?。！？](?:\s*\[(?=[^\]]*\bSource\b)[^\]]+\])?(?=\s|$)|$)",
    re.IGNORECASE,
)


def validate_answer_citations(
    question: str,
    answer: str,
    chunks: list[RetrievedChunk],
) -> str:
    """답변의 Source 순서·페이지를 검사하고 필요한 경우만 인용을 고친다."""
    answer = _strip_answer_heading(answer)
    answer = _normalize_structural_citations(answer, chunks)
    # 이미 유효한 답변에는 불필요한 모델 호출을 하지 않는다.
    if not chunks or NO_SOURCE_PATTERN.match(answer) or not answer_needs_citation_repair(answer, chunks):
        CITATION_VALIDATION_REQUESTS.labels(status="skipped").inc()
        return answer

    messages = [
        {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
        {
            "role": "user",
            "content": _build_validation_request(question, answer, chunks),
        },
    ]
    started_at = time.perf_counter()
    try:
        response = LLMClient().chat_completion(
            messages,
            temperature=0.0,
            operation="citation_validation",
        )
        repaired = _normalize_repaired_answer(response)
    except Exception:
        logger.warning("Citation validation failed; using the original answer", exc_info=True)
        CITATION_VALIDATION_REQUESTS.labels(status="error").inc()
        return answer
    finally:
        CITATION_VALIDATION_DURATION.observe(time.perf_counter() - started_at)

    if not repaired:
        CITATION_VALIDATION_REQUESTS.labels(status="invalid").inc()
        return answer
    # 복구가 전부 거부해도 유효한 인용 문장은 보존한다.
    if NO_SOURCE_PATTERN.match(repaired):
        grounded_fallback = _grounded_claim_fallback(question, answer, chunks)
        if grounded_fallback is not None:
            logger.warning(
                "Citation validation rejected grounded claims; preserving cited subset"
            )
            CITATION_VALIDATION_REQUESTS.labels(status="partial_fallback").inc()
            return grounded_fallback
        CITATION_VALIDATION_REQUESTS.labels(status="no_source").inc()
        return repaired
    if _has_invalid_citation(repaired, chunks) or not valid_cited_source_indexes(repaired, chunks):
        logger.warning("Citation validation returned invalid source references")
        CITATION_VALIDATION_REQUESTS.labels(status="invalid").inc()
        return answer

    status = "unchanged" if repaired == answer.strip() else "repaired"
    CITATION_VALIDATION_REQUESTS.labels(status=status).inc()
    return repaired


def _normalize_structural_citations(
    answer: str,
    chunks: list[RetrievedChunk],
) -> str:
    """Source 순서를 유지하며 생략된 페이지와 잘못 붙은 청크 표기를 정리한다."""
    def add_page(match: re.Match) -> str:
        """페이지 없는 Source 표기에 해당 순서의 청크 페이지를 붙인다."""
        source_index = int(match.group("source")) - 1
        if not 0 <= source_index < len(chunks):
            return match.group(0)
        page = chunks[source_index].page_start
        if page is None:
            return match.group(0)
        return f"Source {source_index + 1}, Page {page}"

    normalized = BARE_SOURCE_PATTERN.sub(add_page, answer)
    normalized = CITATION_ITEM_PATTERN.sub(
        lambda match: _citation_with_chunk_page(match, chunks),
        normalized,
    )
    return CHUNK_SUFFIX_PATTERN.sub("", normalized)


def _citation_with_chunk_page(
    match: re.Match,
    chunks: list[RetrievedChunk],
) -> str:
    """인용 페이지를 Source 순서에 대응하는 실제 청크 범위로 맞춘다."""
    source_index = int(match.group("source")) - 1
    if not 0 <= source_index < len(chunks):
        return match.group(0)
    chunk = chunks[source_index]
    if chunk.page_start is None:
        return match.group(0)
    page = str(chunk.page_start)
    if chunk.page_end is not None and chunk.page_end != chunk.page_start:
        page = f"{chunk.page_start}-{chunk.page_end}"
    return f"Source {source_index + 1}, Page {page}"


def answer_needs_citation_repair(answer: str, chunks: list[RetrievedChunk]) -> bool:
    """모든 실질 주장에 유효한 Source·페이지 인용이 있는지 확인한다."""
    if _has_invalid_citation(answer, chunks):
        return True
    if not valid_cited_source_indexes(answer, chunks):
        return True

    for raw_line in answer.splitlines():
        for claim in _claim_segments(raw_line):
            if not _is_substantive_claim_line(claim):
                continue
            if not valid_cited_source_indexes(claim, chunks):
                return True
    return False


def valid_cited_source_indexes(answer: str, chunks: list[RetrievedChunk]) -> list[int]:
    """답변에서 실제 청크 페이지와 일치하는 Source 순번만 모은다."""
    indexes: list[int] = []
    seen: set[int] = set()
    for match in _citation_item_matches(answer):
        source_index = int(match.group("source")) - 1
        if not 0 <= source_index < len(chunks):
            continue
        chunk = chunks[source_index]
        cited_start = int(match.group("start"))
        cited_end = int(match.group("end")) if match.group("end") else None
        if not _page_matches(chunk, cited_start, cited_end):
            continue
        if source_index in seen:
            continue
        seen.add(source_index)
        indexes.append(source_index)
    return indexes


def _page_matches(
    chunk: RetrievedChunk,
    cited_start: int,
    cited_end: int | None,
) -> bool:
    """인용 페이지 범위가 해당 Source 청크와 같은지 확인한다."""
    if chunk.page_start is None or cited_start != chunk.page_start:
        return False
    if cited_end is None:
        return True
    expected_end = chunk.page_end if chunk.page_end is not None else chunk.page_start
    return cited_end == expected_end


def _has_invalid_citation(answer: str, chunks: list[RetrievedChunk]) -> bool:
    """그룹 밖 Source나 범위를 벗어난 인용이 하나라도 있는지 찾는다."""
    text_without_groups = CITATION_GROUP_PATTERN.sub("", answer)
    if SOURCE_TOKEN_PATTERN.search(text_without_groups):
        return True
    for group in CITATION_GROUP_PATTERN.finditer(answer):
        matches = list(CITATION_ITEM_PATTERN.finditer(group.group("body")))
        if not matches:
            return True
        remainder = CITATION_ITEM_PATTERN.sub("", group.group("body"))
        if re.sub(r"[;\s]+", "", remainder):
            return True
        for match in matches:
            source_index = int(match.group("source")) - 1
            if not 0 <= source_index < len(chunks):
                return True
            cited_start = int(match.group("start"))
            cited_end = int(match.group("end")) if match.group("end") else None
            if not _page_matches(chunks[source_index], cited_start, cited_end):
                return True
    return False


def _citation_item_matches(answer: str):
    """대괄호 인용 그룹 안의 Source 항목을 순서대로 순회한다."""
    for group in CITATION_GROUP_PATTERN.finditer(answer):
        yield from CITATION_ITEM_PATTERN.finditer(group.group("body"))


def _is_substantive_claim_line(line: str) -> bool:
    """제목·코드가 아닌 인용 필요한 실질 주장인지 판정한다."""
    if not line or line.startswith("```"):
        return False
    if line.startswith("#"):
        return False
    without_prefix = MARKDOWN_PREFIX_PATTERN.sub("", line).strip()
    without_citations = CITATION_GROUP_PATTERN.sub("", without_prefix)
    without_citations = re.sub(r"[\[\];,]", " ", without_citations).strip()
    if not without_citations or without_citations.endswith(":"):
        return False
    return len(WORD_PATTERN.findall(without_citations)) >= 12


def _claim_segments(line: str) -> list[str]:
    """한 줄을 문장 단위 주장으로 나눠 개별 인용을 검사하게 한다."""
    normalized = line.strip()
    if not normalized:
        return []
    segments = [match.group(0).strip() for match in CLAIM_SEGMENT_PATTERN.finditer(normalized)]
    return [segment for segment in segments if segment]


def _grounded_claim_fallback(
    question: str,
    answer: str,
    chunks: list[RetrievedChunk],
) -> str | None:
    """과도한 복구가 NO_SOURCE를 내면 유효 인용 주장만 남긴다."""
    grounded_claims: list[str] = []
    seen: set[str] = set()
    for raw_line in answer.splitlines():
        for claim in _claim_segments(raw_line):
            if _has_invalid_citation(claim, chunks):
                continue
            if not valid_cited_source_indexes(claim, chunks):
                continue
            normalized = claim.strip()
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            grounded_claims.append(normalized)

    if not grounded_claims:
        return None
    limitation = (
        "업로드된 자료에서는 위 내용까지만 확인됩니다. 나머지 부분을 판단하려면 "
        "질문의 구체적인 상황을 추가로 알려주세요."
        if re.search(r"[가-힣]", question)
        else (
            "The uploaded material supports only the statements above. Please provide "
            "more details about the specific situation for the remaining parts."
        )
    )
    return "\n".join([*grounded_claims, "", limitation])


def _build_validation_request(
    question: str,
    answer: str,
    chunks: list[RetrievedChunk],
) -> str:
    """질문·제한된 컨텍스트·초안을 인용 복구 요청으로 조립한다."""
    context = build_retrieval_context(chunks)[:MAX_VALIDATION_CONTEXT_CHARS]
    return (
        f"[Question]\n{question}\n\n"
        f"[Context]\n{context}\n\n"
        f"[Draft answer]\n{answer}\n\n"
        "[Revised answer]"
    )


def _normalize_repaired_answer(response: str) -> str:
    """모델 복구 응답의 코드 펜스와 답변 제목을 제거한다."""
    normalized = response.strip()
    if normalized.startswith("```"):
        normalized = re.sub(r"^```(?:markdown|text)?\s*", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\s*```$", "", normalized)
    return _strip_answer_heading(normalized)


def _strip_answer_heading(answer: str) -> str:
    """모델이 덧붙인 ANSWER 계열 머리말을 제거한다."""
    normalized = re.sub(
        r"^\s*(?:#{1,6}\s*)?\[?\s*(?:REVISED\s+)?ANSWER\s*\]?\s*:?\s*",
        "",
        answer,
        flags=re.IGNORECASE,
    )
    return normalized.strip()
