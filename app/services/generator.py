from dataclasses import dataclass

from app.clients.vllm_client import VLLMClient
from app.schemas.chat import SourceRef
from app.services.prompt_builder import build_tutor_messages
from app.services.retriever import RetrievedChunk


@dataclass(frozen=True)
class GeneratedAnswer:
    answer: str
    sources: list[SourceRef]


def generate_answer(question: str, chunks: list[RetrievedChunk]) -> GeneratedAnswer:
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

    messages = build_tutor_messages(question, chunks)
    answer = VLLMClient().chat_completion(messages)
    return GeneratedAnswer(answer=answer, sources=sources)
