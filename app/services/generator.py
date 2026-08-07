import re
from collections.abc import Iterator
from dataclasses import dataclass

from app.clients.vllm_client import VLLMClient
from app.schemas.chat import SourceRef
from app.services.citation_validator import (
    valid_cited_source_indexes,
    validate_answer_citations,
)
from app.services.prompt_builder import build_rag_messages
from app.services.retriever import RetrievedChunk

NO_SOURCE_MARKER_PATTERN = re.compile(r"^\s*\[{1,2}\s*NO_SOURCE\b\s*\]{0,2}", re.IGNORECASE)
SOURCE_CITATION_PATTERN = re.compile(r"\bSource\s+(\d+)\b", re.IGNORECASE)
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
EMPTY_CONTEXT_ANSWER = (
    "업로드된 자료에서 관련 내용을 찾지 못했습니다. "
    "질문을 조금 더 구체적으로 바꾸거나, 해당 내용이 포함된 자료를 업로드해 주세요."
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
    ) -> None:
        self.question = question
        self.chunks = chunks
        self.history = history
        self.generated: GeneratedAnswer | None = None
        self.revision: str | None = None

    def __iter__(self) -> Iterator[str]:
        if not self.chunks:
            self.generated = GeneratedAnswer(answer=EMPTY_CONTEXT_ANSWER, sources=[])
            yield EMPTY_CONTEXT_ANSWER
            return

        messages = build_rag_messages(self.question, self.chunks, self.history)
        normalizer = _StreamingSourceNormalizer()
        for raw_delta in VLLMClient().stream_chat_completion(messages, operation="answer"):
            yield from normalizer.push(raw_delta)
        yield from normalizer.finish()
        raw_answer = normalizer.answer
        answer = (
            validate_answer_citations(self.question, raw_answer, self.chunks)
            if normalizer.has_grounded_source
            else raw_answer
        )
        answer, has_grounded_source = _normalize_source_decision(answer)
        self.revision = answer if answer != raw_answer else None
        self.generated = GeneratedAnswer(
            answer=answer,
            sources=(
                _sources_for_citations(answer, self.chunks)
                if has_grounded_source
                else []
            ),
        )


def generate_answer(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[dict[str, str]] | None = None,
) -> GeneratedAnswer:
    if not chunks:
        return GeneratedAnswer(answer=EMPTY_CONTEXT_ANSWER, sources=[])

    messages = build_rag_messages(question, chunks, history)
    answer = VLLMClient().chat_completion(messages, operation="answer")
    answer, has_grounded_source = _normalize_source_decision(answer)
    if has_grounded_source:
        answer = validate_answer_citations(question, answer, chunks)
        answer, has_grounded_source = _normalize_source_decision(answer)
    return GeneratedAnswer(
        answer=answer,
        sources=_sources_for_citations(answer, chunks) if has_grounded_source else [],
    )


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
