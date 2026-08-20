from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.dependencies import ensure_retrieval_writes_available, get_current_user, get_db
from app.models.user import User
from app.schemas.documents import DocumentListResponse, DocumentResponse, DocumentUploadResponse
from app.services import document_processor, document_service
from app.services.document_service import DocumentDeleteConflictError, DocumentNotFoundError
from app.services.upload_validation import EncryptedPDFError, InvalidPDFError, UploadTooLargeError

router = APIRouter(prefix="/documents", tags=["documents"])


def _to_response(document) -> DocumentResponse:
    return DocumentResponse(
        document_id=document.id,
        title=document.title,
        status=document.status,
        created_at=document.created_at,
        error_message=document.error_message,
    )


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(ensure_retrieval_writes_available),
) -> DocumentUploadResponse:
    if file.content_type not in {"application/pdf", "application/x-pdf"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF uploads are supported")
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PDF filename must end with .pdf")

    try:
        document = await document_service.create_document_from_upload(db, user.id, file)
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except EncryptedPDFError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except InvalidPDFError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    # The durable row exists before indexing starts, so startup recovery can resume it.
    background_tasks.add_task(document_processor.process_document, document.id)
    return DocumentUploadResponse(document_id=document.id, status=document.status)


@router.get("", response_model=DocumentListResponse)
def list_documents(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentListResponse:
    documents = document_service.list_documents(db, user.id)
    return DocumentListResponse(documents=[_to_response(document) for document in documents])


@router.get("/{document_id}/file", response_class=FileResponse)
def get_document_file(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    try:
        document = document_service.get_document(db, document_id, user.id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc

    file_path = Path(document.file_path)
    if not document.file_path or not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file not found")

    filename = Path(document.title).name or f"document-{document.id}.pdf"
    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=filename,
        content_disposition_type="inline",
    )


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentResponse:
    try:
        document = document_service.get_document(db, document_id, user.id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc
    return _to_response(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(ensure_retrieval_writes_available),
) -> Response:
    try:
        document_service.delete_document(db, document_id, user.id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc
    except DocumentDeleteConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document cannot be deleted while processing",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
