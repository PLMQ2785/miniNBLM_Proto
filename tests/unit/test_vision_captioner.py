from app.clients.vllm_client import VLLMClient
from app.services.pdf_parser import ParsedPage
from app.services import vision_captioner
from app.services.vision_captioner import (
    build_vision_search_text,
    enrich_pages_with_vision_captions,
    parse_vision_caption,
    should_caption_page,
)


def _page(**metadata) -> ParsedPage:
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
    caption = parse_vision_caption(
        '{"summary":"diagram \\udbcb","visible_text":["value \\udbcb"],"tables":[],'
        '"diagram_relations":[],"key_values":[],"limitations":[],'
        '"confidence":0.5}'
    )

    assert "\udbcb" not in caption["summary"]
    caption["summary"].encode("utf-8")
    caption["visible_text"][0].encode("utf-8")


def test_risk_only_selection_skips_low_risk_mixed_page() -> None:
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
    monkeypatch.setattr(
        vision_captioner,
        "render_pdf_page_data_url",
        lambda *args: "data:image/png;base64,AAAA",
    )
    monkeypatch.setattr(
        VLLMClient,
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
    monkeypatch.setattr(
        vision_captioner,
        "render_pdf_page_data_url",
        lambda *args: "data:image/png;base64,AAAA",
    )
    monkeypatch.setattr(
        VLLMClient,
        "chat_completion",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("vision unavailable")),
    )

    result = enrich_pages_with_vision_captions("manual.pdf", [_page()], mode="risk_only")

    assert result[0].text == "통신 상태 화면"
    assert result[0].metadata["vision_caption"]["status"] == "failed"
    assert result[0].metadata["text_only_incomplete"] is True


def test_invalid_caption_is_repaired_once(monkeypatch) -> None:
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
        assert kwargs["response_format"]["type"] == "json_schema"
        return next(responses)

    monkeypatch.setattr(VLLMClient, "chat_completion", respond)

    result = enrich_pages_with_vision_captions("manual.pdf", [_page()], mode="risk_only")

    assert result[0].metadata["vision_caption"]["status"] == "completed"
    assert result[0].metadata["vision_caption"]["repaired"] is True
