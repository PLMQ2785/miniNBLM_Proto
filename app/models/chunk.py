from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("chunks_document_idx", "document_id"),
        Index("chunks_page_idx", "document_id", "page_start", "page_end"),
        Index(
            "chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("documents.id"), nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    content_type: Mapped[str] = mapped_column(Text, nullable=False, default="text", server_default="text")
    source_refs: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    chunk_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document = relationship("Document", back_populates="chunks")


Index(
    "chunks_content_trgm_gist",
    Chunk.content,
    postgresql_using="gist",
    postgresql_ops={"content": "gist_trgm_ops"},
)
