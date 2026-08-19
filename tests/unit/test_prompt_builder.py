from app.services.prompt_builder import (
    MAX_GENERATION_CONTEXT_CHARS,
    build_rag_messages,
    build_retrieval_context,
    build_system_message,
    build_user_message,
    select_generation_chunks,
)
from app.services.evidence_coverage import (
    EvidenceMatrix,
    EvidenceMatrixGoal,
    EvidenceReference,
)
from app.services.retriever import RetrievedChunk


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=1,
        document_id=2,
        document_title="guide.pdf",
        content="버전 관리는 변경 이력을 기록한다.",
        page_start=3,
        page_end=3,
        score=0.9,
        source_refs={"page": 3},
    )


def test_build_role_messages_use_generic_rag_contract() -> None:
    system_message = build_system_message()
    user_message = build_user_message("핵심은?", [_chunk()])

    assert system_message["role"] == "system"
    assert "범용 RAG 어시스턴트" in system_message["content"]
    assert "간호" not in system_message["content"]
    assert user_message["role"] == "user"
    assert "[Source 1]" in user_message["content"]
    assert "Evidence Modality: text" in user_message["content"]
    assert "[Question]\n핵심은?" in user_message["content"]


def test_user_message_marks_vision_caption_evidence() -> None:
    chunk = _chunk()
    vision_chunk = RetrievedChunk(
        **{**chunk.__dict__, "content_type": "vision_caption"},
    )

    message = build_user_message("화면의 값은?", [vision_chunk])

    assert "Evidence Modality: vision_caption" in message["content"]


def test_system_prompt_allows_only_fully_supported_multi_source_inference() -> None:
    content = build_system_message()["content"]

    assert "여러 Context에 모두 명시" in content
    assert "결론이 직접 도출" in content
    assert "자료에 없는 중간 전제" in content
    assert "확인 가능한 사실이 Context에 하나도 없을 때만" in content
    assert "각 사실이나 비교 항목 바로 뒤" in content
    assert "비교 대상 양쪽의 근거" in content
    assert "관련 사실까지 버리라는 뜻이 아니다" in content
    assert "각 SUPPORTED 항목을 빠짐없이" in content
    assert "단위당 비율과 적용 횟수·기간" in content
    assert "vision_caption" in content


def test_build_rag_messages_places_history_before_current_question() -> None:
    messages = build_rag_messages(
        "그 다음은?",
        [_chunk()],
        [
            {"role": "user", "content": "먼저 무엇을 하나요?"},
            {"role": "assistant", "content": "위험 요인을 확인합니다."},
        ],
    )

    assert [message["role"] for message in messages] == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "먼저 무엇을 하나요?"
    assert "[Context]" in messages[-1]["content"]
    assert "그 다음은?" in messages[-1]["content"]


def test_user_message_includes_partial_evidence_matrix() -> None:
    message = build_user_message(
        "감점을 구분해 주세요.",
        [_chunk()],
        EvidenceMatrix(
            status="partial",
            goals=(
                EvidenceMatrixGoal(
                    "g1",
                    "지연 감점률",
                    "supported",
                    (EvidenceReference(1, "guide.pdf", 3, 3),),
                ),
                EvidenceMatrixGoal("g2", "모델 불일치 정량 감점", "missing"),
            ),
        ),
    )

    assert "[Evidence Matrix]" in message["content"]
    assert "GOAL g1 [SUPPORTED]: 지연 감점률" in message["content"]
    assert "document=guide.pdf; pages=3-3; chunk=1" in message["content"]
    assert "GOAL g2 [MISSING]: 모델 불일치 정량 감점" in message["content"]


def test_user_message_preserves_positionally_interpreted_literals() -> None:
    message = build_user_message(
        "응답 `LB05 03 NLNNB`를 위치별로 해석해 주세요.",
        [_chunk()],
    )

    assert "[Literal Fidelity]" in message["content"]
    assert "PRESERVE EXACTLY: `LB05 03 NLNNB`" in message["content"]
    assert "copy each character from left to right" in message["content"]


def test_user_message_requires_exclusion_removal_before_workflow_commands() -> None:
    message = build_user_message(
        "secret.txt를 .gitignore에 넣었는데 stash하려면 어떻게 하나요?",
        [_chunk()],
    )

    assert "[Workflow Preconditions]" in message["content"]
    assert "state how that exclusion is removed" in message["content"]
    assert "execution order" in message["content"]


def test_user_message_includes_insufficient_matrix_for_qualified_answers() -> None:
    message = build_user_message(
        "자료가 뒷받침하는 내용과 확정할 수 없는 부분을 구분해 주세요.",
        [_chunk()],
        EvidenceMatrix(
            status="insufficient",
            goals=(EvidenceMatrixGoal("g1", "구체 적용 조건", "missing"),),
        ),
    )

    assert "Coverage: INSUFFICIENT" in message["content"]
    assert "GOAL g1 [MISSING]: 구체 적용 조건" in message["content"]


def test_generation_context_is_bounded_and_prioritizes_matrix_evidence() -> None:
    chunks = [
        RetrievedChunk(
            chunk_id=index,
            document_id=10,
            document_title=f"document-{index}.pdf",
            content=str(index) * 4000,
            page_start=index,
            page_end=index,
            score=1.0 - index / 10,
            source_refs={"page": index},
        )
        for index in range(1, 6)
    ]
    matrix = EvidenceMatrix(
        status="complete",
        goals=(
            EvidenceMatrixGoal(
                "g1",
                "후순위 핵심 근거",
                "supported",
                (EvidenceReference(5, "document-5.pdf", 5, 5),),
            ),
        ),
    )

    selected = select_generation_chunks(chunks, matrix)
    context = build_retrieval_context(selected)

    assert selected[0].chunk_id == 5
    assert len(selected) < len(chunks)
    assert len(context) <= MAX_GENERATION_CONTEXT_CHARS


def test_generation_context_prefers_distinct_pages_before_adjacent_duplicates() -> None:
    page_numbers = (7, 7, 6, 6, 5, 4)
    content_lengths = (3500, 2000, 3500, 1500, 3500, 1800)
    chunks = [
        RetrievedChunk(
            chunk_id=index,
            document_id=10,
            document_title="paper.pdf",
            content="x" * content_length,
            page_start=page,
            page_end=page,
            score=1.0 - index / 10,
            source_refs={"page": page},
        )
        for index, (page, content_length) in enumerate(
            zip(page_numbers, content_lengths, strict=True),
            start=1,
        )
    ]
    matrix = EvidenceMatrix(
        status="complete",
        goals=(
            EvidenceMatrixGoal(
                "g1",
                "page 7 evidence",
                "supported",
                (EvidenceReference(1, "paper.pdf", 7, 7),),
            ),
            EvidenceMatrixGoal(
                "g2",
                "page 6 evidence",
                "supported",
                (EvidenceReference(3, "paper.pdf", 6, 6),),
            ),
        ),
    )

    selected = select_generation_chunks(chunks, matrix)

    assert [chunk.chunk_id for chunk in selected] == [1, 3, 5, 6]
