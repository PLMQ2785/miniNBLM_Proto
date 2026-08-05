from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, SmallInteger, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RetrievalPresetRecord(Base):
    __tablename__ = "retrieval_presets"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_size_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_overlap_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SearchAlgorithmRecord(Base):
    __tablename__ = "search_algorithms"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RetrievalConfiguration(Base):
    __tablename__ = "retrieval_configuration"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    active_preset_key: Mapped[str] = mapped_column(
        Text,
        ForeignKey("retrieval_presets.key", ondelete="RESTRICT"),
        nullable=False,
    )
    pending_preset_key: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("retrieval_presets.key", ondelete="RESTRICT"),
    )
    active_search_algorithm_key: Mapped[str] = mapped_column(
        Text,
        ForeignKey("search_algorithms.key", ondelete="RESTRICT"),
        nullable=False,
        default="dense",
        server_default="dense",
    )
    index_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    maintenance_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    active_preset = relationship("RetrievalPresetRecord", foreign_keys=[active_preset_key])
    pending_preset = relationship("RetrievalPresetRecord", foreign_keys=[pending_preset_key])
    active_search_algorithm = relationship("SearchAlgorithmRecord")


class ReindexJob(Base):
    __tablename__ = "reindex_jobs"
    __table_args__ = (
        Index("reindex_jobs_status_idx", "status", "created_at"),
        Index("reindex_jobs_requested_by_idx", "requested_by", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    requested_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    source_preset_key: Mapped[str] = mapped_column(Text, ForeignKey("retrieval_presets.key"), nullable=False)
    target_preset_key: Mapped[str] = mapped_column(Text, ForeignKey("retrieval_presets.key"), nullable=False)
    target_index_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default="pending")
    reindex_documents: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rebuild_vector_index: Mapped[bool] = mapped_column(Boolean, nullable=False)
    runtime_settings_changed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    total_documents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    completed_documents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_documents: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    requester = relationship("User")
