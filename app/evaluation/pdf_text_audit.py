from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import fitz


def audit_pdf(path: Path, root: Path) -> dict:
    pages = []
    with fitz.open(path) as document:
        for page_number, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            blocks = page.get_text("dict").get("blocks", [])
            image_count = sum(block.get("type") == 1 for block in blocks)
            drawing_count = len(page.get_drawings())
            pages.append(
                {
                    "page": page_number,
                    "text_chars": len(text),
                    "image_count": image_count,
                    "drawing_count": drawing_count,
                    "risk": _page_risk(len(text), image_count, drawing_count),
                }
            )
    risk_counts = Counter(page["risk"] for page in pages)
    return {
        "group": path.parent.name,
        "path": str(path.relative_to(root)),
        "title": path.name,
        "page_count": len(pages),
        "text_chars": sum(page["text_chars"] for page in pages),
        "risk_counts": dict(sorted(risk_counts.items())),
        "pages": pages,
    }


def audit_root(root: Path) -> dict:
    resolved_root = root.resolve()
    documents = [
        audit_pdf(path, resolved_root)
        for path in sorted(resolved_root.glob("*/*.pdf"))
    ]
    return {
        "schema_version": 1,
        "root": str(resolved_root),
        "document_count": len(documents),
        "page_count": sum(document["page_count"] for document in documents),
        "documents": documents,
    }


def _page_risk(text_chars: int, image_count: int, drawing_count: int) -> str:
    if text_chars == 0:
        return "empty_text"
    if text_chars < 100 and (image_count > 0 or drawing_count >= 10):
        return "visual_heavy"
    if text_chars < 100:
        return "low_text"
    if image_count > 0 or drawing_count >= 10:
        return "mixed"
    return "text"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit extractable text and visual-risk indicators in PDF pages"
    )
    parser.add_argument("root", type=Path, nargs="?", default=Path("sample"))
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = audit_root(args.root)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(args.output)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
