import fitz

from app.services.pdf_parser import extract_pages


def test_extract_pages_removes_repeated_margins_and_records_visual_risk(tmp_path) -> None:
    pdf_path = tmp_path / "layout.pdf"
    document = fitz.open()
    for page_number in range(1, 4):
        page = document.new_page(width=600, height=800)
        page.insert_text((50, 40), "Repeated course header")
        page.insert_text((50, 200), f"Unique body content {page_number}")
        page.insert_text((290, 770), str(page_number))
        if page_number == 2:
            page.draw_rect(fitz.Rect(100, 300, 300, 500))
    document.save(pdf_path)
    document.close()

    pages = extract_pages(str(pdf_path))

    assert len(pages) == 3
    assert "Repeated course header" not in pages[0].text
    assert "Unique body content 1" in pages[0].text
    assert pages[0].text.strip() != "1"
    assert pages[1].metadata["drawing_count"] > 0
    assert pages[1].metadata["has_visual_content"] is True
    assert pages[1].metadata["visual_evidence_risk"] == "visual_heavy"
    assert pages[1].metadata["language_hint"] == "en"
