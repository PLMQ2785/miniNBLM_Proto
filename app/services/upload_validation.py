from pathlib import Path

import fitz


class UploadValidationError(Exception):
    """업로드 검증 실패를 API 오류로 구분하는 공통 예외다."""
    pass


class UploadTooLargeError(UploadValidationError):
    """저장 제한을 넘긴 업로드를 413 응답으로 전달한다."""
    pass


class InvalidPDFError(UploadValidationError):
    """읽을 수 없는 PDF를 업로드 단계에서 거부한다."""
    pass


class EncryptedPDFError(UploadValidationError):
    """암호가 필요한 PDF를 지원 대상에서 제외한다."""
    pass


def validate_saved_pdf(file_path: str) -> None:
    """저장된 파일을 열어 암호 여부와 PDF 페이지 구성을 검증한다."""
    try:
        document = fitz.open(file_path)
    except (fitz.FileDataError, RuntimeError) as exc:
        raise InvalidPDFError("The uploaded file is not a readable PDF") from exc

    with document:
        if document.needs_pass:
            raise EncryptedPDFError("Password-protected PDFs are not supported")
        if not document.is_pdf or document.page_count < 1:
            raise InvalidPDFError("The uploaded file is not a readable PDF")


def has_pdf_signature(file_path: str) -> bool:
    """저장 파일이 PDF 매직 바이트로 시작하는지 확인한다."""
    with Path(file_path).open("rb") as source:
        return source.read(5) == b"%PDF-"
