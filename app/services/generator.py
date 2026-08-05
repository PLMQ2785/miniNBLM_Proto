import re
from dataclasses import dataclass

from app.clients.vllm_client import VLLMClient
from app.schemas.chat import SourceRef
from app.services.prompt_builder import build_tutor_messages
from app.services.retriever import RetrievedChunk

NO_SOURCE_MARKER_PATTERN = re.compile(r"^\s*\[\[\s*NO_SOURCE\b\s*\]{0,2}", re.IGNORECASE)
NO_SOURCE_PREFIXES = (
    "업로드된 자료에서 확인되지 않습니다",
    "업로드된 자료에서 관련 내용을 찾지 못했습니다",
)


@dataclass(frozen=True)
class GeneratedAnswer:
    answer: str
    sources: list[SourceRef]


def generate_answer(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[dict[str, str]] | None = None,
) -> GeneratedAnswer:
    sources = [
        SourceRef(
            document_id=chunk.document_id,
            document_title=chunk.document_title,
            page=chunk.page_start,
            chunk_id=chunk.chunk_id,
        )
        for chunk in chunks
    ]

    if not chunks:
        return GeneratedAnswer(
            answer=(
                "업로드된 자료에서 관련 내용을 찾지 못했습니다. "
                "질문을 조금 더 구체적으로 바꾸거나, 해당 내용이 포함된 자료를 업로드해 주세요."
            ),
            sources=[],
        )

    messages = build_tutor_messages(question, chunks, history)
    answer = VLLMClient().chat_completion(messages)
    answer, has_grounded_source = _normalize_source_decision(answer)
    return GeneratedAnswer(answer=answer, sources=sources if has_grounded_source else [])


def _normalize_source_decision(answer: str) -> tuple[str, bool]:
    normalized = answer.strip()
    marker_match = NO_SOURCE_MARKER_PATTERN.match(normalized)
    if marker_match:
        visible_answer = normalized[marker_match.end():].lstrip(" :-\n")
        return visible_answer or "업로드된 자료에서 확인되지 않습니다.", False
    if normalized.startswith(NO_SOURCE_PREFIXES):
        return answer, False
    return answer, True
