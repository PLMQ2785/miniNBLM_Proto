from pathlib import Path
import shutil
from uuid import uuid4

from fastapi import UploadFile

from app.config import settings
from app.services.upload_validation import InvalidPDFError, UploadTooLargeError, has_pdf_signature


class LocalStorage:
    """문서별 디렉터리에서 업로드 원본을 보관하고 제거한다."""
    def __init__(self, upload_dir: str | None = None) -> None:
        """설정값 또는 지정 경로를 업로드 저장소 루트로 사용한다."""
        self.upload_dir = Path(upload_dir or settings.upload_dir)

    async def save_upload_file(self, file: UploadFile, document_id: int) -> str:
        """업로드를 제한 크기로 스트리밍 저장하고 PDF 서명을 검증한다."""
        document_dir = self.upload_dir / "documents" / str(document_id)
        document_dir.mkdir(parents=True, exist_ok=True)
        destination = document_dir / f"original-{uuid4().hex}.pdf"
        total_bytes = 0

        # Content-Length를 신뢰하지 않고 스트리밍 중 실제 바이트를 센다.
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
        """문서 식별자에 대응하는 저장 디렉터리 경로를 반환한다."""
        return str(self.upload_dir / "documents" / str(document_id))

    def delete_document(self, document_id: int) -> None:
        """계정·문서 삭제 뒤 해당 문서의 로컬 파일을 모두 제거한다."""
        document_dir = self.upload_dir / "documents" / str(document_id)
        if document_dir.exists():
            shutil.rmtree(document_dir)
