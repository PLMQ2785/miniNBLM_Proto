from pathlib import Path

from app.services.evidence_coverage import EvidenceMatrix
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
                    f"Evidence Modality: {chunk.content_type}",
                    f"Text Evidence Quality: {_format_evidence_quality(chunk)}",
                    "Content:",
                    chunk.content,
                ]
            )
        )
    return "\n\n".join(sections)


def build_system_message() -> dict[str, str]:
    return {"role": "system", "content": load_rag_system_prompt()}


def build_user_message(
    question: str,
    chunks: list[RetrievedChunk],
    evidence_matrix: EvidenceMatrix | None = None,
) -> dict[str, str]:
    context = build_retrieval_context(chunks)
    matrix = _format_evidence_matrix(evidence_matrix)
    content = f"[Context]\n{context}\n\n{matrix}[Question]\n{question}\n\n[Answer]"
    return {"role": "user", "content": content}


def build_rag_messages(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[dict[str, str]] | None = None,
    evidence_matrix: EvidenceMatrix | None = None,
) -> list[dict[str, str]]:
    return [
        build_system_message(),
        *(history or []),
        build_user_message(question, chunks, evidence_matrix),
    ]


def _format_page(chunk: RetrievedChunk) -> str:
    if chunk.page_start is None:
        return "unknown"
    if chunk.page_end is None or chunk.page_end == chunk.page_start:
        return str(chunk.page_start)
    return f"{chunk.page_start}-{chunk.page_end}"


def _format_evidence_quality(chunk: RetrievedChunk) -> str:
    metadata = chunk.source_refs.get("page_metadata", {})
    if not isinstance(metadata, dict):
        return "unknown"
    risk = metadata.get("visual_evidence_risk", "unknown")
    if chunk.content_type == "vision_caption":
        vision = metadata.get("vision_caption", {})
        confidence = vision.get("confidence") if isinstance(vision, dict) else None
        return f"vision caption; confidence={confidence if confidence is not None else 'unknown'}"
    if metadata.get("text_only_incomplete"):
        return f"{risk}; visual content may be absent from extracted text"
    return str(risk)


def _format_evidence_matrix(matrix: EvidenceMatrix | None) -> str:
    if matrix is None or matrix.status in {"unchecked", "insufficient"}:
        return ""
    lines = [f"Coverage: {matrix.status.upper()}"]
    lines.extend(f"SUPPORTED: {goal}" for goal in matrix.supported_goals)
    lines.extend(f"MISSING: {goal}" for goal in matrix.missing_goals)
    return "[Evidence Matrix]\n" + "\n".join(lines) + "\n\n"
