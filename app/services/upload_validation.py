from pathlib import Path

import fitz


class UploadValidationError(Exception):
    pass


class UploadTooLargeError(UploadValidationError):
    pass


class InvalidPDFError(UploadValidationError):
    pass


class EncryptedPDFError(UploadValidationError):
    pass


def validate_saved_pdf(file_path: str) -> None:
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
    with Path(file_path).open("rb") as source:
        return source.read(5) == b"%PDF-"
