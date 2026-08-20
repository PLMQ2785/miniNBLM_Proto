from pathlib import Path
import shutil
from uuid import uuid4

from fastapi import UploadFile

from app.config import settings
from app.services.upload_validation import InvalidPDFError, UploadTooLargeError, has_pdf_signature


class LocalStorage:
    def __init__(self, upload_dir: str | None = None) -> None:
        self.upload_dir = Path(upload_dir or settings.upload_dir)

    async def save_upload_file(self, file: UploadFile, document_id: int) -> str:
        document_dir = self.upload_dir / "documents" / str(document_id)
        document_dir.mkdir(parents=True, exist_ok=True)
        destination = document_dir / f"original-{uuid4().hex}.pdf"
        total_bytes = 0

        # Count bytes while streaming; Content-Length is not trusted.
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > settings.max_upload_bytes:
                    raise UploadTooLargeError(
                        f"PDF exceeds the {settings.max_upload_bytes} byte upload limit"
                    )
                output.write(chunk)

        await file.seek(0)
        if total_bytes == 0 or not has_pdf_signature(str(destination)):
            raise InvalidPDFError("The uploaded file does not have a valid PDF signature")
        return str(destination)

    def get_document_path(self, document_id: int) -> str:
        return str(self.upload_dir / "documents" / str(document_id))

    def delete_document(self, document_id: int) -> None:
        document_dir = self.upload_dir / "documents" / str(document_id)
        if document_dir.exists():
            shutil.rmtree(document_dir)
