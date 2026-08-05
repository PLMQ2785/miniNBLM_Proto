from pathlib import Path

from app.services.retriever import RetrievedChunk


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "tutor_system_prompt.txt"


def load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_context(chunks: list[RetrievedChunk]) -> str:
    sections: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        page = _format_page(chunk)
        sections.append(
            "\n".join(
                [
                    f"[Source {index}]",
                    f"Document ID: {chunk.document_id}",
                    f"Page: {page}",
                    f"Chunk ID: {chunk.chunk_id}",
                    "Content:",
                    chunk.content,
                ]
            )
        )
    return "\n\n".join(sections)


def build_tutor_messages(question: str, chunks: list[RetrievedChunk]) -> list[dict[str, str]]:
    context = build_context(chunks)
    system_prompt = load_system_prompt()
    user_prompt = f"[Context]\n{context}\n\n[Question]\n{question}\n\n[Answer]"
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _format_page(chunk: RetrievedChunk) -> str:
    if chunk.page_start is None:
        return "unknown"
    if chunk.page_end is None or chunk.page_end == chunk.page_start:
        return str(chunk.page_start)
    return f"{chunk.page_start}-{chunk.page_end}"
