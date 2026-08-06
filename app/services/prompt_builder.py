from pathlib import Path

from app.services.retriever import RetrievedChunk


RAG_SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "rag_system_prompt.txt"
)


def load_rag_system_prompt() -> str:
    return RAG_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def build_retrieval_context(chunks: list[RetrievedChunk]) -> str:
    sections: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        page = _format_page(chunk)
        sections.append(
            "\n".join(
                [
                    f"[Source {index}]",
                    f"Document: {chunk.document_title}",
                    f"Document ID: {chunk.document_id}",
                    f"Page: {page}",
                    f"Chunk ID: {chunk.chunk_id}",
                    "Content:",
                    chunk.content,
                ]
            )
        )
    return "\n\n".join(sections)


def build_system_message() -> dict[str, str]:
    return {"role": "system", "content": load_rag_system_prompt()}


def build_user_message(question: str, chunks: list[RetrievedChunk]) -> dict[str, str]:
    context = build_retrieval_context(chunks)
    content = f"[Context]\n{context}\n\n[Question]\n{question}\n\n[Answer]"
    return {"role": "user", "content": content}


def build_rag_messages(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    return [
        build_system_message(),
        *(history or []),
        build_user_message(question, chunks),
    ]


def _format_page(chunk: RetrievedChunk) -> str:
    if chunk.page_start is None:
        return "unknown"
    if chunk.page_end is None or chunk.page_end == chunk.page_start:
        return str(chunk.page_start)
    return f"{chunk.page_start}-{chunk.page_end}"
