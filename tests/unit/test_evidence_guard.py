from app.services.evidence_guard import assess_evidence_answerability
from app.services.retriever import RetrievedChunk


def _visual_chunk(page: int) -> RetrievedChunk:
    """텍스트만으로 불완전한 시각 중심 페이지 청크를 만든다."""
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
    """지정 도표 페이지의 정확한 계산은 시각 근거 없이는 차단하는지 보장한다."""
    decision = assess_evidence_answerability(
        "20페이지 상태 다이어그램에서 최종 변수 x의 값과 각 단계 계산을 설명해 주세요.",
        [_visual_chunk(20)],
    )

    assert decision.answerable is False
    assert decision.pages == (20,)


def test_general_question_about_mixed_page_is_not_blanket_blocked() -> None:
    """혼합 페이지의 일반 텍스트 질문까지 일괄 차단하지 않는지 보장한다."""
    decision = assess_evidence_answerability(
        "20페이지에서 형상관리의 정의를 설명해 주세요.",
        [_visual_chunk(20)],
    )

    assert decision.answerable is True


def test_exact_visual_question_is_allowed_when_caption_is_in_context() -> None:
    """같은 페이지의 시각 캡션이 있으면 정확한 시각 질문을 허용하는지 보장한다."""
    visual = _visual_chunk(20)
    caption = RetrievedChunk(
        chunk_id=2,
        document_id=2,
        document_title="slides.pdf",
        content="[Vision evidence] 최종 x = 4",
        page_start=20,
        page_end=20,
        score=0.85,
        source_refs=visual.source_refs,
        content_type="vision_caption",
    )

    decision = assess_evidence_answerability(
        "20페이지 상태 다이어그램에서 최종 변수 x의 값을 정확히 계산해 주세요.",
        [visual, caption],
    )

    assert decision.answerable is True
