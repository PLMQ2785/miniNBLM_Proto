from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document


def create_document(
    db: Session,
    owner_id: int,
    title: str,
    file_path: str,
    mime_type: str | None,
) -> Document:
    """사용자 소유 문서를 추가하고 호출자 트랜잭션에서 식별자를 확정한다."""
    document = Document(
        owner_id=owner_id,
        title=title,
        file_path=file_path,
        mime_type=mime_type,
        status="uploaded",
    )
    db.add(document)
    db.flush()
    return document


def get_document_by_id(db: Session, document_id: int) -> Document | None:
    """소유자 제한 없이 삭제되지 않은 문서를 내부 작업용으로 조회한다."""
    statement = select(Document).where(Document.id == document_id, Document.deleted_at.is_(None))
    return db.scalar(statement)


def get_document(
    db: Session,
    document_id: int,
    owner_id: int,
    *,
    for_update: bool = False,
) -> Document | None:
    """소유권과 삭제 상태를 강제하며 필요하면 문서 행을 잠근다."""
    # 라우터 밖 호출도 안전하도록 소유권과 삭제 상태를 쿼리에서 제한한다.
    statement = select(Document).where(
        Document.id == document_id,
        Document.owner_id == owner_id,
        Document.deleted_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def list_documents(db: Session, owner_id: int) -> list[Document]:
    """사용자가 소유한 활성 문서를 최신순으로 조회한다."""
    statement = (
        select(Document)
        .where(Document.owner_id == owner_id, Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
    )
    return list(db.scalars(statement))


def list_all_documents(db: Session) -> list[Document]:
    """백그라운드 작업용으로 모든 활성 문서를 조회한다."""
    statement = select(Document).where(Document.deleted_at.is_(None)).order_by(Document.id)
    return list(db.scalars(statement))


def list_interrupted_documents(db: Session) -> list[Document]:
    """복구 작업이 처리할 중단 문서를 잠가 조회한다."""
    statement = (
        select(Document)
        .where(
            Document.deleted_at.is_(None),
            Document.status.in_(("uploaded", "processing")),
        )
        .order_by(Document.id)
        .with_for_update()
    )
    return list(db.scalars(statement))


def has_active_documents(db: Session) -> bool:
    """진행 중인 활성 문서가 있는지 트랜잭션 안에서 확인한다."""
    statement = select(Document.id).where(
        Document.deleted_at.is_(None),
        Document.status.in_(("uploaded", "processing")),
    ).limit(1)
    return db.scalar(statement) is not None


def update_file_path(db: Session, document: Document, file_path: str) -> Document:
    """문서 파일 경로를 바꾸고 호출자 트랜잭션에 반영한다."""
    document.file_path = file_path
    document.updated_at = datetime.now(UTC)
    db.flush()
    return document


def update_status(
    db: Session,
    document: Document,
    status: str,
    error_message: str | None = None,
) -> Document:
    """문서 처리 상태와 오류를 바꾸고 호출자 트랜잭션에 반영한다."""
    document.status = status
    document.error_message = error_message
    document.updated_at = datetime.now(UTC)
    db.flush()
    return document


def update_index_metadata(
    db: Session,
    document: Document,
    preset_key: str,
    index_version: int,
) -> Document:
    """문서의 검색 프리셋·색인 버전을 호출자 트랜잭션에 반영한다."""
    document.indexed_preset_key = preset_key
    document.index_version = index_version
    db.flush()
    return document


def delete_document(db: Session, document: Document) -> None:
    """문서를 삭제 예약하고 커밋은 호출자에게 맡긴다."""
    db.delete(document)
    db.flush()
