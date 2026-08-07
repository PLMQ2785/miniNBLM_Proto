from app.services.evidence_guard import assess_text_only_answerability
from app.services.retriever import RetrievedChunk


def _visual_chunk(page: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=1,
        document_id=2,
        document_title="slides.pdf",
        content="이벤트 순서 e1, e2, e4와 질문 텍스트",
        page_start=page,
        page_end=page,
        score=0.9,
        source_refs={
            "pages": [page],
            "page_metadata": {
                "has_visual_content": True,
                "visual_evidence_risk": "visual_heavy",
                "text_only_incomplete": True,
            },
        },
    )


def test_exact_calculation_from_named_diagram_page_is_blocked() -> None:
    decision = assess_text_only_answerability(
        "20페이지 상태 다이어그램에서 최종 변수 x의 값과 각 단계 계산을 설명해 주세요.",
        [_visual_chunk(20)],
    )

    assert decision.answerable is False
    assert decision.pages == (20,)


def test_general_question_about_mixed_page_is_not_blanket_blocked() -> None:
    decision = assess_text_only_answerability(
        "20페이지에서 형상관리의 정의를 설명해 주세요.",
        [_visual_chunk(20)],
    )

    assert decision.answerable is True
