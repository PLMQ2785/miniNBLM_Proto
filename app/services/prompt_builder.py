from pathlib import Path
import re

from app.services.evidence_coverage import EvidenceMatrix
from app.services.retriever import RetrievedChunk


RAG_SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "rag_system_prompt.txt"
)
BACKTICK_LITERAL_PATTERN = re.compile(r"`([^`\n]{1,120})`")
EXCLUDED_STATE_PATTERN = re.compile(
    r"(?:\.gitignore|\bignored?\b|\bexcluded?\b|무시|제외)",
    re.IGNORECASE,
)
MAX_GENERATION_CONTEXT_CHARS = 14_000


def load_rag_system_prompt() -> str:
    """모든 RAG 답변에 공통으로 적용할 시스템 지침을 읽는다."""
    return RAG_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def _format_chunk_section(index: int, chunk: RetrievedChunk) -> str:
    """인용 번호와 메타데이터를 포함한 완전한 Source 블록을 만든다."""
    page = _format_page(chunk)
    return "\n".join(
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


def select_generation_chunks(
    chunks: list[RetrievedChunk],
    evidence_matrix: EvidenceMatrix | None = None,
) -> list[RetrievedChunk]:
    """근거 행렬 우선순위와 Source 순서를 지키며 컨텍스트를 14,000자로 고른다."""
    evidence_chunk_ids = (
        {
            reference.chunk_id
            for goal in evidence_matrix.goals
            for reference in goal.evidence
        }
        if evidence_matrix is not None
        else set()
    )
    # 행렬 근거, 서로 다른 페이지, 같은 페이지의 인접 청크 순으로 Source를 둔다.
    evidence_chunks = [
        chunk for chunk in chunks if chunk.chunk_id in evidence_chunk_ids
    ]
    covered_locations = {
        (chunk.document_id, chunk.page_start, chunk.page_end)
        for chunk in evidence_chunks
    }
    distinct_page_chunks: list[RetrievedChunk] = []
    repeated_page_chunks: list[RetrievedChunk] = []
    for chunk in chunks:
        if chunk.chunk_id in evidence_chunk_ids:
            continue
        location = (chunk.document_id, chunk.page_start, chunk.page_end)
        if location not in covered_locations:
            distinct_page_chunks.append(chunk)
            covered_locations.add(location)
        else:
            repeated_page_chunks.append(chunk)
    prioritized = [
        *evidence_chunks,
        *distinct_page_chunks,
        *repeated_page_chunks,
    ]
    # 인용 대상이 잘리지 않도록 Source 블록은 통째로 포함하거나 제외한다.
    selected: list[RetrievedChunk] = []
    used_chars = 0
    for chunk in prioritized:
        section = _format_chunk_section(len(selected) + 1, chunk)
        section_chars = len(section) + (2 if selected else 0)
        if selected and used_chars + section_chars > MAX_GENERATION_CONTEXT_CHARS:
            continue
        selected.append(chunk)
        used_chars += section_chars
    return selected


def build_retrieval_context(chunks: list[RetrievedChunk]) -> str:
    """선택된 청크 순서를 그대로 Source 번호가 있는 컨텍스트로 만든다."""
    return "\n\n".join(
        _format_chunk_section(index, chunk)
        for index, chunk in enumerate(chunks, start=1)
    )


def build_system_message() -> dict[str, str]:
    """RAG 시스템 프롬프트를 모델 메시지 형식으로 감싼다."""
    return {"role": "system", "content": load_rag_system_prompt()}


def build_user_message(
    question: str,
    chunks: list[RetrievedChunk],
    evidence_matrix: EvidenceMatrix | None = None,
) -> dict[str, str]:
    """컨텍스트·근거 행렬·질문 제약을 한 사용자 메시지로 조립한다."""
    context = build_retrieval_context(chunks)
    matrix = _format_evidence_matrix(evidence_matrix)
    literals = _format_literal_constraints(question)
    workflow = _format_workflow_constraints(question)
    content = (
        f"[Context]\n{context}\n\n{matrix}{literals}{workflow}"
        f"[Question]\n{question}\n\n[Answer]"
    )
    return {"role": "user", "content": content}


def build_rag_messages(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[dict[str, str]] | None = None,
    evidence_matrix: EvidenceMatrix | None = None,
) -> list[dict[str, str]]:
    """시스템 지침, 대화 이력, 현재 RAG 질문을 호출 순서로 묶는다."""
    return [
        build_system_message(),
        *(history or []),
        build_user_message(question, chunks, evidence_matrix),
    ]


def _format_page(chunk: RetrievedChunk) -> str:
    """청크의 페이지 범위를 인용 표기에 맞게 표시한다."""
    if chunk.page_start is None:
        return "unknown"
    if chunk.page_end is None or chunk.page_end == chunk.page_start:
        return str(chunk.page_start)
    return f"{chunk.page_start}-{chunk.page_end}"


def _format_evidence_quality(chunk: RetrievedChunk) -> str:
    """시각 자료 누락 위험을 모델이 판단할 수 있는 문구로 바꾼다."""
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


def _format_literal_constraints(question: str) -> str:
    """질문의 백틱 리터럴을 원문 그대로 보존하도록 제약을 만든다."""
    literals = tuple(dict.fromkeys(BACKTICK_LITERAL_PATTERN.findall(question)))
    if not literals:
        return ""
    rendered = ", ".join(f"`{literal}`" for literal in literals)
    return (
        "[Literal Fidelity]\n"
        f"PRESERVE EXACTLY: {rendered}\n"
        "If a literal is interpreted by character or field position, copy each character "
        "from left to right before mapping its meaning. Never substitute a Context example.\n\n"
    )


def _format_evidence_matrix(matrix: EvidenceMatrix | None) -> str:
    """목표별 충족 상태와 근거 청크를 프롬프트용 행렬로 표시한다."""
    if matrix is None or matrix.status == "unchecked":
        return ""
    lines = [f"Coverage: {matrix.status.upper()}"]
    for goal in matrix.goals:
        references = ", ".join(
            (
                f"document={evidence.document_title}; "
                f"pages={evidence.page_start}-{evidence.page_end}; "
                f"chunk={evidence.chunk_id}"
            )
            for evidence in goal.evidence
        )
        suffix = f" | evidence: {references}" if references else ""
        lines.append(
            f"GOAL {goal.goal_id} [{goal.status.upper()}]: "
            f"{goal.description}{suffix}"
        )
    return "[Evidence Matrix]\n" + "\n".join(lines) + "\n\n"


def _format_workflow_constraints(question: str) -> str:
    """제외 상태를 먼저 해제해야 하는 작업 순서 제약을 추가한다."""
    if not EXCLUDED_STATE_PATTERN.search(question):
        return ""
    return (
        "[Workflow Preconditions]\n"
        "The question starts with an ignored or excluded item. Before any command that "
        "requires inclusion, tracking, or processing, state how that exclusion is removed. "
        "Then list later state transitions and commands in execution order.\n\n"
    )
