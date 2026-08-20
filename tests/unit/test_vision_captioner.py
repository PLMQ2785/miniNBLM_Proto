from app.clients.llm_client import LLMClient
from app.services.pdf_parser import ParsedPage
from app.services import vision_captioner
from app.services.vision_captioner import (
    build_vision_search_text,
    enrich_pages_with_vision_captions,
    parse_vision_caption,
    should_caption_page,
)


def _page(**metadata) -> ParsedPage:
    """Vision 설명 대상이 되는 시각 중심 페이지를 만든다."""
    return ParsedPage(
        page_number=19,
        text="통신 상태 화면",
        metadata={
            "has_visual_content": True,
            "visual_evidence_risk": "visual_heavy",
            "text_only_incomplete": True,
            "table_count": 0,
            "drawing_count": 1,
            **metadata,
        },
    )


def test_parse_caption_and_build_search_text() -> None:
    """Vision JSON을 정규화하고 검색 가능한 텍스트로 펼친다."""
    caption = parse_vision_caption(
        """```json
        {
          "summary": "Tera Term response screen",
          "visible_text": ["LB05-01 NLNNN"],
          "tables": [],
          "diagram_relations": [],
          "key_values": ["ID = 01"],
          "limitations": [],
          "confidence": 1.2
        }
        ```"""
    )

    assert caption["confidence"] == 1.0
    assert "LB05-01 NLNNN" in build_vision_search_text(caption)
    assert "ID = 01" in build_vision_search_text(caption)


def test_parse_caption_replaces_invalid_unicode_surrogates() -> None:
    """잘못된 유니코드 서로게이트를 안전한 문자로 치환한다."""
    caption = parse_vision_caption(
        '{"summary":"diagram \\udbcb","visible_text":["value \\udbcb"],"tables":[],'
        '"diagram_relations":[],"key_values":[],"limitations":[],'
        '"confidence":0.5}'
    )

    assert "\udbcb" not in caption["summary"]
    caption["summary"].encode("utf-8")
    caption["visible_text"][0].encode("utf-8")


def test_risk_only_selection_skips_low_risk_mixed_page() -> None:
    """위험 기반 모드는 불완전하지 않은 혼합 페이지를 건너뛴다."""
    page = _page(
        visual_evidence_risk="mixed",
        text_only_incomplete=False,
        drawing_count=2,
    )

    assert should_caption_page(page, "risk_only") is False
    assert should_caption_page(page, "all_visual") is True


def test_enrich_page_stores_caption_without_image_data(
    monkeypatch,
) -> None:
    """완성된 Vision 설명만 메타데이터에 남기고 이미지 원문은 버린다."""
    monkeypatch.setattr(
        vision_captioner,
        "render_pdf_page_data_url",
        lambda *args: "data:image/png;base64,AAAA",
    )
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: (
            '{"summary":"Terminal response","visible_text":["LB05-01 NLNNN"],'
            '"tables":[],"diagram_relations":[],"key_values":[],'
            '"limitations":[],"confidence":0.95}'
        ),
    )

    result = enrich_pages_with_vision_captions("manual.pdf", [_page()], mode="risk_only")

    vision = result[0].metadata["vision_caption"]
    assert vision["status"] == "completed"
    assert vision["confidence"] == 0.95
    assert "LB05-01 NLNNN" in vision["search_text"]
    assert "base64" not in str(vision)
    assert result[0].metadata["text_only_incomplete"] is True


def test_caption_failure_preserves_page_for_text_only_indexing(monkeypatch) -> None:
    """Vision 실패에도 텍스트 페이지를 색인 가능한 상태로 보존한다."""
    monkeypatch.setattr(
        vision_captioner,
        "render_pdf_page_data_url",
        lambda *args: "data:image/png;base64,AAAA",
    )
    monkeypatch.setattr(
        LLMClient,
        "chat_completion",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("vision unavailable")),
    )

    result = enrich_pages_with_vision_captions("manual.pdf", [_page()], mode="risk_only")

    assert result[0].text == "통신 상태 화면"
    assert result[0].metadata["vision_caption"]["status"] == "failed"
    assert result[0].metadata["text_only_incomplete"] is True


def test_invalid_caption_is_repaired_once(monkeypatch) -> None:
    """형식이 잘못된 Vision 응답은 JSON 스키마로 한 번만 복구한다."""
    monkeypatch.setattr(
        vision_captioner,
        "render_pdf_page_data_url",
        lambda *args: "data:image/png;base64,AAAA",
    )
    responses = iter(
        [
            "Visible text is LB05 01 NLNNN",
            (
                '{"summary":"Terminal response","visible_text":["LB05 01 NLNNN"],'
                '"tables":[],"diagram_relations":[],"key_values":[],'
                '"limitations":[],"confidence":0.8}'
            ),
        ]
    )

    def respond(*args, **kwargs):
        """복구 요청의 JSON 스키마 사용을 확인하고 다음 응답을 반환한다."""
        assert kwargs["response_format"]["type"] == "json_schema"
        return next(responses)

    monkeypatch.setattr(LLMClient, "chat_completion", respond)

    result = enrich_pages_with_vision_captions("manual.pdf", [_page()], mode="risk_only")

    assert result[0].metadata["vision_caption"]["status"] == "completed"
    assert result[0].metadata["vision_caption"]["repaired"] is True
