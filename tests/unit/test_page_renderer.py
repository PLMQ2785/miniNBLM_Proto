import base64

import fitz
import pytest

from app.services.page_renderer import render_pdf_page_data_url


def test_render_pdf_page_returns_png_data_url(tmp_path) -> None:
    """지정한 PDF 페이지를 PNG 데이터 URL로 렌더링한다."""
    pdf_path = tmp_path / "page.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Vision evidence")
    document.save(pdf_path)
    document.close()

    data_url = render_pdf_page_data_url(str(pdf_path), 1, dpi=72)

    prefix, encoded = data_url.split(",", 1)
    assert prefix == "data:image/png;base64"
    assert base64.b64decode(encoded).startswith(b"\x89PNG")


def test_render_pdf_page_rejects_invalid_page_number(tmp_path) -> None:
    """PDF 범위를 벗어난 페이지 번호는 렌더링 전에 거부한다."""
    pdf_path = tmp_path / "page.pdf"
    document = fitz.open()
    document.new_page()
    document.save(pdf_path)
    document.close()

    with pytest.raises(ValueError, match="page_number"):
        render_pdf_page_data_url(str(pdf_path), 2)
