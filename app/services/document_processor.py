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
    """복구 작업이 문서 인덱싱을 독립 백그라운드 스레드로 재개하게 한다."""
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
    """PDF에서 텍스트·시각 근거를 추출해 페이지와 검색 청크를 원자적으로 인덱싱한다."""
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

        # 재인덱싱은 파생 데이터만 교체하고 원본 PDF는 보존한다.
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
        # 시각 캡션에는 처리 시작 시점의 소유자 endpoint snapshot을 쓴다.
        endpoint = language_model_service.get_user_endpoint(owner)
        with language_model_service.use_endpoint(endpoint):
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
        # 페이지·청크·최종 상태는 한 트랜잭션으로 함께 공개한다.
        db.commit()
        return True
    except Exception as exc:
        # 조회와 재시작 복구에 쓸 실패 사유를 DB에 남긴다.
        db.rollback()
        document = document_repository.get_document_by_id(db, document_id)
        if document is not None:
            document_repository.update_status(db, document, "failed", str(exc))
            db.commit()
        logger.exception("Document processing failed for document_id=%s", document_id)
        return False
    finally:
        db.close()
