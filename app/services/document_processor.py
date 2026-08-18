import logging
import threading

from app.clients.embedding_client import EmbeddingClient
from app.database import SessionLocal
from app.repositories import (
    chat_repository,
    chunk_repository,
    document_repository,
    page_repository,
    retrieval_config_repository,
    user_repository,
)
from app.services.chunker import chunk_pages
from app.services.pdf_parser import extract_pages
from app.services.vision_captioner import enrich_pages_with_vision_captions
from app.services import language_model_service

logger = logging.getLogger(__name__)


def start_document_worker(document_id: int, *, reset_existing: bool = False) -> None:
    worker = threading.Thread(
        target=process_document,
        kwargs={"document_id": document_id, "reset_existing": reset_existing},
        name=f"document-index-{document_id}",
        daemon=True,
    )
    worker.start()


def process_document(
    document_id: int,
    *,
    preset_key: str | None = None,
    index_version: int | None = None,
    reset_existing: bool = False,
) -> bool:
    db = SessionLocal()
    try:
        document = document_repository.get_document_by_id(db, document_id)
        if document is None:
            logger.warning("Document %s not found for processing", document_id)
            return False

        if preset_key is None or index_version is None:
            configuration = retrieval_config_repository.get_configuration(db)
            preset_key = configuration.active_preset_key
            index_version = configuration.index_version
        preset = retrieval_config_repository.get_preset(db, preset_key)
        if preset is None:
            raise ValueError(f"Unknown retrieval preset: {preset_key}")

        if reset_existing:
            chat_repository.delete_sessions_for_document(db, document.id)
            chunk_repository.delete_chunks(db, document.id)
            page_repository.delete_pages(db, document.id)

        document_repository.update_status(db, document, "processing")
        db.commit()

        pages = extract_pages(document.file_path)
        owner = user_repository.get_user_by_id(db, document.owner_id)
        if owner is None:
            raise ValueError("Document owner not found")
        endpoint_key = language_model_service.get_user_endpoint_key(owner)
        with language_model_service.use_endpoint(endpoint_key):
            pages = enrich_pages_with_vision_captions(document.file_path, pages)
        if not pages:
            raise ValueError("No pages found in PDF")

        page_repository.create_pages(db, document.id, pages)
        chunks = chunk_pages(
            pages,
            chunk_size=preset.chunk_size_chars,
            chunk_overlap=preset.chunk_overlap_chars,
            document_id=document.id,
        )
        if not chunks:
            raise ValueError("No searchable text or visual evidence found in PDF")

        embeddings = EmbeddingClient().embed_documents([chunk.content for chunk in chunks])
        chunk_repository.create_chunks(db, document.id, chunks, embeddings)

        document_repository.update_index_metadata(db, document, preset_key, index_version)
        document_repository.update_status(db, document, "indexed")
        db.commit()
        return True
    except Exception as exc:
        db.rollback()
        document = document_repository.get_document_by_id(db, document_id)
        if document is not None:
            document_repository.update_status(db, document, "failed", str(exc))
            db.commit()
        logger.exception("Document processing failed for document_id=%s", document_id)
        return False
    finally:
        db.close()
