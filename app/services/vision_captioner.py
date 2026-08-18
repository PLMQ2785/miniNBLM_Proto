from dataclasses import replace
import json
import logging
from pathlib import Path
import re
from typing import Any

from app.clients.llm_client import LLMClient
from app.config import settings
from app.services.page_renderer import render_pdf_page_data_url
from app.services.pdf_parser import ParsedPage


logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "vision_caption_system_prompt.txt"
REPAIR_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "vision_caption_repair_system_prompt.txt"
)
CAPTION_FIELDS = (
    "visible_text",
    "tables",
    "diagram_relations",
    "key_values",
    "limitations",
)
VISION_CAPTION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "vision_caption",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string"},
                **{
                    field: {"type": "array", "items": {"type": "string"}}
                    for field in CAPTION_FIELDS
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["summary", *CAPTION_FIELDS, "confidence"],
        },
    },
}


def enrich_pages_with_vision_captions(
    pdf_path: str,
    pages: list[ParsedPage],
    *,
    mode: str | None = None,
) -> list[ParsedPage]:
    selected_mode = mode or settings.vision_caption_mode
    if selected_mode == "disabled":
        return pages

    enriched: list[ParsedPage] = []
    client = LLMClient()
    if not client.supports_vision:
        raise ValueError(f"LLM endpoint {client.endpoint_key!r} does not support vision")
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    for page in pages:
        if not should_caption_page(page, selected_mode):
            enriched.append(page)
            continue

        metadata = dict(page.metadata)
        try:
            image_url = render_pdf_page_data_url(
                pdf_path,
                page.page_number,
                settings.vision_caption_dpi,
            )
            caption, repaired = _request_vision_caption(
                client,
                system_prompt,
                image_url,
                page.page_number,
            )
        except Exception as exc:
            logger.warning(
                "Vision caption failed; preserving text-only page",
                extra={"page_number": page.page_number, "error_type": type(exc).__name__},
                exc_info=True,
            )
            metadata["vision_caption"] = {
                "status": "failed",
                "version": settings.vision_caption_version,
                "model": client.model,
                "error_type": type(exc).__name__,
            }
        else:
            metadata["vision_caption"] = {
                "status": "completed",
                "version": settings.vision_caption_version,
                "model": client.model,
                "confidence": caption["confidence"],
                "repaired": repaired,
                "data": caption,
                "search_text": build_vision_search_text(caption),
            }
        enriched.append(replace(page, metadata=metadata))
    return enriched


def should_caption_page(page: ParsedPage, mode: str) -> bool:
    if mode == "disabled":
        return False
    metadata = page.metadata
    has_visual = bool(metadata.get("has_visual_content")) or int(
        metadata.get("table_count", 0)
    ) > 0
    if mode == "all_visual":
        return has_visual
    if mode != "risk_only":
        raise ValueError(f"Unsupported vision caption mode: {mode}")
    return bool(metadata.get("text_only_incomplete")) or int(
        metadata.get("table_count", 0)
    ) > 0 or (
        metadata.get("visual_evidence_risk") == "mixed"
        and int(metadata.get("drawing_count", 0)) >= 3
    )


def _request_vision_caption(
    client: LLMClient,
    system_prompt: str,
    image_url: str,
    page_number: int,
) -> tuple[dict[str, Any], bool]:
    response = client.chat_completion(
        [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {
                        "type": "text",
                        "text": (
                            f"Extract visual evidence from PDF page {page_number}. "
                            "Return only the required JSON object."
                        ),
                    },
                ],
            },
        ],
        temperature=0.0,
        operation="vision_caption",
        response_format=VISION_CAPTION_RESPONSE_FORMAT,
    )
    try:
        return parse_vision_caption(response), False
    except (json.JSONDecodeError, ValueError):
        repaired = client.chat_completion(
            [
                {
                    "role": "system",
                    "content": REPAIR_PROMPT_PATH.read_text(encoding="utf-8"),
                },
                {
                    "role": "user",
                    "content": f"[Draft]\n{response[:12_000]}\n\n[JSON]",
                },
            ],
            temperature=0.0,
            operation="vision_caption",
            response_format=VISION_CAPTION_RESPONSE_FORMAT,
        )
        return parse_vision_caption(repaired), True


def parse_vision_caption(response: str) -> dict[str, Any]:
    normalized = response.strip()
    if normalized.startswith("```"):
        normalized = re.sub(r"^```(?:json)?\s*", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\s*```$", "", normalized)
    start = normalized.find("{")
    end = normalized.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Vision caption response is not a JSON object")
    payload = json.loads(normalized[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Vision caption response must be an object")

    summary = _normalize_text(payload.get("summary"))
    fields = {field: _normalize_string_list(payload.get(field)) for field in CAPTION_FIELDS}
    if not summary and not any(fields[field] for field in CAPTION_FIELDS[:-1]):
        raise ValueError("Vision caption contains no searchable evidence")
    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Vision caption confidence must be numeric") from exc
    return {
        "summary": summary,
        **fields,
        "confidence": max(0.0, min(confidence, 1.0)),
    }


def build_vision_search_text(caption: dict[str, Any]) -> str:
    sections: list[str] = ["[Vision evidence]"]
    if caption["summary"]:
        sections.append(f"Summary: {caption['summary']}")
    labels = {
        "visible_text": "Visible text",
        "tables": "Tables",
        "diagram_relations": "Diagram relations",
        "key_values": "Key values",
        "limitations": "Limitations",
    }
    for field, label in labels.items():
        values = caption[field]
        if values:
            sections.append(f"{label}:\n" + "\n".join(f"- {value}" for value in values))
    return "\n".join(sections)


def _normalize_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    valid_unicode = value.encode("utf-8", errors="replace").decode("utf-8")
    return " ".join(valid_unicode.split())


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if (text := _normalize_text(item)):
            normalized.append(text)
    return normalized
