import base64

import fitz


def render_pdf_page_data_url(pdf_path: str, page_number: int, dpi: int = 144) -> str:
    """시각 모델 입력용으로 지정 PDF 페이지를 PNG 데이터 URL로 렌더링한다."""
    if page_number < 1:
        raise ValueError("page_number must be at least 1")

    with fitz.open(pdf_path) as document:
        if page_number > document.page_count:
            raise ValueError(f"page_number exceeds PDF page count: {page_number}")
        page = document[page_number - 1]
        scale = dpi / 72
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        encoded = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
    return f"data:image/png;base64,{encoded}"
