import re
from collections.abc import Iterator
from dataclasses import dataclass

from app.clients.llm_client import LLMClient
from app.schemas.chat import SourceRef
from app.services.citation_validator import (
    valid_cited_source_indexes,
    validate_answer_citations,
)
from app.services.prompt_builder import (
    EXCLUDED_STATE_PATTERN,
    build_rag_messages,
    build_retrieval_context,
    select_generation_chunks,
)
from app.services.evidence_guard import assess_evidence_answerability
from app.services.evidence_coverage import EvidenceMatrix
from app.services.retriever import RetrievedChunk

NO_SOURCE_MARKER_PATTERN = re.compile(r"^\s*\[{1,2}\s*NO_SOURCE\b\s*\]{0,2}", re.IGNORECASE)
SOURCE_CITATION_PATTERN = re.compile(r"\bSource\s+(\d+)\b", re.IGNORECASE)
EXCLUSION_RELEASE_PATTERN = re.compile(
    r"(?:해제|제거|삭제|목록에서\s*빼|\bremove\b|\bunignore\b)",
    re.IGNORECASE,
)
NO_SOURCE_PREFIXES = (
    "업로드된 자료에서 확인되지 않습니다",
    "업로드된 자료에서 관련 내용을 찾지 못했습니다",
)
NO_SOURCE_MARKER_CANDIDATES = (
    "[[NO_SOURCE]]",
    "[[NO_SOURCE]",
    "[NO_SOURCE]]",
    "[NO_SOURCE]",
)
DEGENERATE_REPETITION_PATTERN = re.compile(r"(.{1,12}?)\1{10,}", re.DOTALL)
BACKTICK_LITERAL_PATTERN = re.compile(r"`([^`\n]{2,120})`")
CHANNEL_RANGE_PATTERN = re.compile(
    r"(?:채널|channel)\s*1\s*[~\-–]\s*(\d+)",
    re.IGNORECASE,
)
LITERAL_CONFUSION_PAIRS = {
    frozenset(pair)
    for pair in (
        ("I", "L"),
        ("I", "1"),
        ("L", "1"),
        ("O", "0"),
        ("B", "8"),
        ("S", "5"),
        ("Z", "2"),
    )
}
LITERAL_FIDELITY_REPAIR_SYSTEM_PROMPT = (
    "You are a literal-fidelity editor. Return only the revised answer. Preserve grounded "
    "claims and citations. For every exact literal listed by the user, copy its characters "
    "left to right and correct every field-by-field or position-by-position interpretation "
    "that does not match those characters. Never replace it with a Context example."
)
EMPTY_CONTEXT_ANSWER = (
    "업로드된 자료에서 관련 내용을 찾지 못했습니다. "
    "질문을 조금 더 구체적으로 바꾸거나, 해당 내용이 포함된 자료를 업로드해 주세요."
)
VISUAL_EVIDENCE_LIMIT_ANSWER = (
    "업로드된 자료에서 확인되지 않습니다. 해당 페이지의 핵심 근거가 이미지, "
    "화면 또는 다이어그램에 포함되어 있으나 이 질문에 필요한 시각 근거가 검색되지 않았습니다."
)
INSUFFICIENT_EVIDENCE_ANSWER = (
    "업로드된 자료만으로는 현재 질문의 구체적인 상황에 맞는 답변을 확정하기 어렵습니다. "
    "수행하려던 작업과 사용한 명령, 발생한 오류, 현재 상태, 되돌릴 대상을 구체적으로 알려주세요."
)


@dataclass(frozen=True)
class GeneratedAnswer:
    answer: str
    sources: list[SourceRef]


class StreamingAnswer:
    def __init__(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        history: list[dict[str, str]] | None = None,
        evidence_matrix: EvidenceMatrix | None = None,
    ) -> None:
        self.question = question
        self.chunks = chunks
        self.history = history
        self.evidence_matrix = evidence_matrix
        self.generated: GeneratedAnswer | None = None
        self.revision: str | None = None

    def __iter__(self) -> Iterator[str]:
        if not self.chunks:
            self.generated = GeneratedAnswer(answer=EMPTY_CONTEXT_ANSWER, sources=[])
            yield EMPTY_CONTEXT_ANSWER
            return

        guard = assess_evidence_answerability(self.question, self.chunks)
        if not guard.answerable:
            self.generated = GeneratedAnswer(answer=VISUAL_EVIDENCE_LIMIT_ANSWER, sources=[])
            yield VISUAL_EVIDENCE_LIMIT_ANSWER
            return
        if _requires_clarification(self.question, self.evidence_matrix):
            self.generated = GeneratedAnswer(answer=INSUFFICIENT_EVIDENCE_ANSWER, sources=[])
            yield INSUFFICIENT_EVIDENCE_ANSWER
            return
        # Prompt, citation checks, and final SourceRef mapping use this same ordering.
        generation_chunks = select_generation_chunks(
            self.chunks,
            self.evidence_matrix,
        )

        messages = build_rag_messages(
            self.question,
            generation_chunks,
            self.history,
            evidence_matrix=self.evidence_matrix,
        )
        # Hold the prefix until NO_SOURCE can be hidden without leaking marker text.
        normalizer = _StreamingSourceNormalizer()
        for raw_delta in LLMClient().stream_chat_completion(messages, operation="answer"):
            yield from normalizer.push(raw_delta)
        yield from normalizer.finish()
        streamed_answer = normalizer.answer
        raw_answer = streamed_answer
        if _has_degenerate_repetition(raw_answer):
            raw_answer = _retry_degenerate_answer(messages, raw_answer)
        answer = (
            validate_answer_citations(self.question, raw_answer, generation_chunks)
            if normalizer.has_grounded_source
            else raw_answer
        )
        answer, has_grounded_source = _normalize_source_decision(answer)
        answer = _repair_literal_fidelity(self.question, answer, generation_chunks)
        answer = _normalize_positional_channel_answer(
            self.question,
            answer,
            generation_chunks,
        )
        answer = _restore_question_literal_fidelity(self.question, answer)
        answer, has_grounded_source = _normalize_source_decision(answer)
        answer = _ensure_exclusion_precondition(self.question, answer)
        # Post-stream repairs are sent as one replacement event.
        self.revision = answer if answer != streamed_answer else None
        self.generated = GeneratedAnswer(
            answer=answer,
            sources=(
                _sources_for_citations(answer, generation_chunks)
                if has_grounded_source
                else []
            ),
        )


def generate_answer(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[dict[str, str]] | None = None,
    evidence_matrix: EvidenceMatrix | None = None,
) -> GeneratedAnswer:
    if not chunks:
        return GeneratedAnswer(answer=EMPTY_CONTEXT_ANSWER, sources=[])

    guard = assess_evidence_answerability(question, chunks)
    if not guard.answerable:
        return GeneratedAnswer(answer=VISUAL_EVIDENCE_LIMIT_ANSWER, sources=[])
    if _requires_clarification(question, evidence_matrix):
        return GeneratedAnswer(answer=INSUFFICIENT_EVIDENCE_ANSWER, sources=[])
    # Keep the synchronous path on the same bounded context as streaming.
    generation_chunks = select_generation_chunks(chunks, evidence_matrix)

    messages = build_rag_messages(
        question,
        generation_chunks,
        history,
        evidence_matrix=evidence_matrix,
    )
    answer = LLMClient().chat_completion(messages, operation="answer")
    if _has_degenerate_repetition(answer):
        answer = _retry_degenerate_answer(messages, answer)
    answer, has_grounded_source = _normalize_source_decision(answer)
    if has_grounded_source:
        answer = validate_answer_citations(question, answer, generation_chunks)
        answer, has_grounded_source = _normalize_source_decision(answer)
    answer = _repair_literal_fidelity(question, answer, generation_chunks)
    answer = _normalize_positional_channel_answer(question, answer, generation_chunks)
    answer = _restore_question_literal_fidelity(question, answer)
    answer, has_grounded_source = _normalize_source_decision(answer)
    answer = _ensure_exclusion_precondition(question, answer)
    return GeneratedAnswer(
        answer=answer,
        sources=_sources_for_citations(answer, generation_chunks) if has_grounded_source else [],
    )

def _requires_clarification(
    question: str,
    evidence_matrix: EvidenceMatrix | None,
) -> bool:
    if evidence_matrix is None or evidence_matrix.status != "insufficient":
        return False
    normalized = " ".join(question.split()).casefold()
    requests_qualified_answer = (
        any(term in normalized for term in ("자료", "문서", "context"))
        and any(term in normalized for term in ("구분", "나누", "separate", "distinguish"))
        and any(
            term in normalized
            for term in ("확정할 수 없", "확인할 수 없", "뒷받침", "근거", "unsupported")
        )
    )
    return not requests_qualified_answer


def _ensure_exclusion_precondition(question: str, answer: str) -> str:
    if (
        not EXCLUDED_STATE_PATTERN.search(question)
        or EXCLUSION_RELEASE_PATTERN.search(answer)
    ):
        return answer
    return (
        "먼저 질문에 명시된 제외·무시 상태를 해제해야 합니다. "
        "그 후 포함·추적에 필요한 다음 단계를 순서대로 진행합니다.\n\n"
        f"{answer}"
    )


def _repair_literal_fidelity(
    question: str,
    answer: str,
    chunks: list[RetrievedChunk],
) -> str:
    literals = [
        literal
        for literal in dict.fromkeys(BACKTICK_LITERAL_PATTERN.findall(question))
        if any(character.isdigit() for character in literal)
        and any(character.isalpha() for character in literal)
    ]
    if not literals:
        return answer
    field_maps = [
        f"- `{literal}` field {field_index}: "
        + ", ".join(
            f"position {position}=`{character}`"
            for position, character in enumerate(field, start=1)
        )
        for literal in literals
        for field_index, field in enumerate(literal.split(), start=1)
    ]
    context = build_retrieval_context(chunks)
    had_citations = SOURCE_CITATION_PATTERN.search(answer) is not None
    detected_errors: list[str] = []
    for _ in range(4):
        try:
            revised = LLMClient().chat_completion(
                [
                    {"role": "system", "content": LITERAL_FIDELITY_REPAIR_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "[Exact literal field maps]\n"
                            + "\n".join(field_maps)
                            + (
                                "\n\n[Detected errors]\n" + "\n".join(detected_errors)
                                if detected_errors
                                else ""
                            )
                            + f"\n\n[Context]\n{context}\n\n"
                            f"[Question]\n{question}\n\n[Draft]\n{answer}\n\n"
                            "[Revised answer]"
                        ),
                    },
                ],
                temperature=0.0,
                operation="literal_fidelity_repair",
            )
        except Exception:
            return answer
        detected_errors = _literal_position_errors(question, revised)
        if had_citations and SOURCE_CITATION_PATTERN.search(revised) is None:
            detected_errors.append("The revised answer removed all required Source citations.")
        if not detected_errors:
            return revised
    return answer


def _normalize_positional_channel_answer(
    question: str,
    answer: str,
    chunks: list[RetrievedChunk],
) -> str:
    range_match = CHANNEL_RANGE_PATTERN.search(question)
    if range_match is None:
        return answer
    position_count = int(range_match.group(1))
    fields = [
        field.upper()
        for literal in BACKTICK_LITERAL_PATTERN.findall(question)
        for field in literal.split()
        if len(field) == position_count and field.isalpha()
    ]
    if len(fields) != 1:
        return answer
    expected = fields[0]
    context = build_retrieval_context(chunks)
    meanings: list[tuple[str, str]] = []
    for position in range(1, position_count + 1):
        match = re.search(
            rf"{position}\s*번\s*채널\s*([가-힣 ]{{1,30}}?)\s*[-–]\s*([A-Za-z]+)",
            context,
        )
        if match is None:
            return answer
        meanings.append((match.group(1).strip(), match.group(2)))

    citation_match = re.search(r"\[Source\s+\d+,\s*Page\s+\d+\]", answer)
    citation = f" {citation_match.group(0)}" if citation_match is not None else ""
    lines = [
        "**1. 채널별 상태 해석**",
        f"`{expected}`의 각 위치는 다음 상태를 의미합니다.{citation}",
    ]
    lines.extend(
        f"* **채널 {position}**: {expected[position - 1]} "
        f"({korean} / {english}){citation}"
        for position, (korean, english) in enumerate(meanings, start=1)
    )
    normalized_section = "\n".join(lines) + "\n"
    section_pattern = re.compile(
        r"\*\*1\.\s*채널별 상태 해석\*\*.*?(?=\n\s*\*\*2\.)",
        re.DOTALL,
    )
    has_section = section_pattern.search(answer) is not None
    normalized = (
        section_pattern.sub(normalized_section, answer, count=1)
        if has_section
        else answer
    )
    if not has_section:
        for position, (korean, english) in enumerate(meanings, start=1):
            line_pattern = re.compile(
                rf"^.*(?:채널\s*{position}|{position}\s*번\s*채널).*$",
                re.MULTILINE,
            )
            replacement = (
                f"* **채널 {position}**: {expected[position - 1]} "
                f"({korean} / {english}){citation}"
            )
            normalized = line_pattern.sub(replacement, normalized, count=1)

    def restore_field(match: re.Match[str]) -> str:
        candidate = match.group(1)
        return expected if set(candidate) <= set(expected) else candidate

    normalized = re.sub(
        r"(?<![A-Z0-9])([A-Z]{3,})(?=`?에서\s*각\s*위치)",
        restore_field,
        normalized,
    )
    normalized = re.sub(r"채\d+널", "채널", normalized)
    return normalized


def _literal_position_errors(question: str, answer: str) -> list[str]:
    range_match = CHANNEL_RANGE_PATTERN.search(question)
    if range_match is None:
        return []
    position_count = int(range_match.group(1))
    fields = [
        field
        for literal in BACKTICK_LITERAL_PATTERN.findall(question)
        for field in literal.split()
        if len(field) == position_count and field.isalpha()
    ]
    if len(fields) != 1:
        return []
    expected = fields[0].upper()
    errors: list[str] = []
    malformed_fields = re.findall(
        r"상태(?:\s*필드)?는\s*`?([A-Z]{3,})`?"
        r"|(?<![A-Z0-9])([A-Z]{3,})(?=에서\s*각\s*위치)",
        answer,
    )
    for groups in malformed_fields:
        candidate = next(value for value in groups if value)
        if candidate != expected and set(candidate) <= set(expected):
            errors.append(f"Positional field `{candidate}` must be `{expected}`.")
    korean_ordinals = ("첫", "두", "세", "네", "다섯")
    for position, expected_character in enumerate(expected, start=1):
        ordinal = korean_ordinals[position - 1] if position <= len(korean_ordinals) else ""
        label_pattern = (
            rf"(?:채널\s*{position}|{position}\s*번\s*채널"
            + (rf"|{ordinal}\s*번째\s*채널" if ordinal else "")
            + r")\**"
        )
        match = re.search(
            rf"{label_pattern}\s*(?:\(([A-Z])\)\s*[:：]|[:：]\s*\**\s*([A-Z])\b)",
            answer,
            re.IGNORECASE,
        )
        if match is None:
            continue
        actual_character = (match.group(1) or match.group(2)).upper()
        if actual_character != expected_character:
            errors.append(
                f"Channel {position} must start with `{expected_character}`, "
                f"not `{actual_character}`."
            )
    return errors


def _restore_question_literal_fidelity(question: str, answer: str) -> str:
    restored = answer
    for literal in dict.fromkeys(BACKTICK_LITERAL_PATTERN.findall(question)):
        if (
            not any(character.isdigit() for character in literal)
            or not any(character.isalpha() for character in literal)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _./:-]*", literal)
        ):
            continue
        candidate_pattern = "".join(
            r"\s+" if character.isspace()
            else r"[A-Za-z0-9]" if character.isalnum()
            else re.escape(character)
            for character in literal
        )

        def restore_candidate(match: re.Match[str]) -> str:
            candidate = re.sub(r"\s+", " ", match.group(0))
            expected = re.sub(r"\s+", " ", literal)
            differences = [
                (actual.upper(), wanted.upper())
                for actual, wanted in zip(candidate, expected, strict=True)
                if actual.upper() != wanted.upper()
            ]
            if (
                len(candidate) == len(expected)
                and len(differences) == 1
                and frozenset(differences[0]) in LITERAL_CONFUSION_PAIRS
            ):
                return literal
            return match.group(0)

        restored = re.sub(
            rf"(?<![A-Za-z0-9]){candidate_pattern}(?![A-Za-z0-9])",
            restore_candidate,
            restored,
        )
    return restored


def _has_degenerate_repetition(answer: str) -> bool:
    return DEGENERATE_REPETITION_PATTERN.search(answer) is not None


def _retry_degenerate_answer(
    messages: list[dict[str, str]],
    fallback_answer: str,
) -> str:
    retry_messages = [dict(message) for message in messages]
    retry_messages[0] = {
        **retry_messages[0],
        "content": (
            retry_messages[0]["content"]
            + "\n15. 같은 문자, 단어 또는 구절을 반복하지 말고 800토큰 이내로 답한다."
        ),
    }
    try:
        retry = LLMClient().chat_completion(retry_messages, operation="answer_retry")
    except Exception:
        retry = fallback_answer
    if not _has_degenerate_repetition(retry):
        return retry
    match = DEGENERATE_REPETITION_PATTERN.search(retry)
    return retry[: match.start()].rstrip() if match else retry


def _normalize_source_decision(answer: str) -> tuple[str, bool]:
    normalized = answer.strip()
    marker_match = NO_SOURCE_MARKER_PATTERN.match(normalized)
    if marker_match:
        visible_answer = normalized[marker_match.end():].lstrip(" :-\n")
        return visible_answer or "업로드된 자료에서 확인되지 않습니다.", False
    if normalized.startswith(NO_SOURCE_PREFIXES):
        return answer, False
    return answer, True


def cited_source_indexes(answer: str, source_count: int) -> list[int]:
    indexes: list[int] = []
    seen: set[int] = set()
    for match in SOURCE_CITATION_PATTERN.finditer(answer):
        source_index = int(match.group(1)) - 1
        if source_index in seen or not 0 <= source_index < source_count:
            continue
        seen.add(source_index)
        indexes.append(source_index)
    return indexes


def _sources_for_citations(answer: str, chunks: list[RetrievedChunk]) -> list[SourceRef]:
    sources: list[SourceRef] = []
    seen_locations: set[tuple[int, int | None]] = set()

    for source_index in valid_cited_source_indexes(answer, chunks):
        chunk = chunks[source_index]
        location = (chunk.document_id, chunk.page_start)
        if location in seen_locations:
            continue
        seen_locations.add(location)
        sources.append(
            SourceRef(
                document_id=chunk.document_id,
                document_title=chunk.document_title,
                page=chunk.page_start,
                chunk_id=chunk.chunk_id,
            )
        )
    return sources


def _detect_stream_source_decision(buffer: str) -> bool | None:
    candidate = buffer.lstrip()
    if not candidate:
        return None

    upper_candidate = candidate.upper()
    if any(marker.startswith(upper_candidate) for marker in NO_SOURCE_MARKER_CANDIDATES):
        return None
    if NO_SOURCE_MARKER_PATTERN.match(candidate):
        return False

    for prefix in NO_SOURCE_PREFIXES:
        if prefix.startswith(candidate):
            return None
        if candidate.startswith(prefix):
            return False
    return True


class _StreamingSourceNormalizer:
    def __init__(self) -> None:
        self.pending = ""
        self.parts: list[str] = []
        self.has_grounded_source: bool | None = None

    @property
    def answer(self) -> str:
        return "".join(self.parts)

    def push(self, delta: str) -> list[str]:
        if self.has_grounded_source is not None:
            self.parts.append(delta)
            return [delta]

        self.pending += delta
        decision = _detect_stream_source_decision(self.pending)
        if decision is None:
            return []

        self.has_grounded_source = decision
        if decision:
            visible = self.pending
        else:
            visible, _ = _normalize_source_decision(self.pending)
        self.pending = ""
        if not visible:
            return []
        self.parts.append(visible)
        return [visible]

    def finish(self) -> list[str]:
        emitted: list[str] = []
        if self.has_grounded_source is None:
            visible, self.has_grounded_source = _normalize_source_decision(self.pending)
            self.pending = ""
            if visible:
                self.parts.append(visible)
                emitted.append(visible)
        if not self.answer and self.has_grounded_source is False:
            fallback = "업로드된 자료에서 확인되지 않습니다."
            self.parts.append(fallback)
            emitted.append(fallback)
        return emitted
