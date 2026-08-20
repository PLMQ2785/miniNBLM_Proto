from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, SmallInteger, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RetrievalPresetRecord(Base):
    """관리 API와 색인 작업이 참조하는 검색 프리셋 레코드다."""
    __tablename__ = "retrieval_presets"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_size_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_overlap_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SearchAlgorithmRecord(Base):
    """관리 API에서 선택할 수 있는 검색 알고리즘 메타데이터다."""
    __tablename__ = "search_algorithms"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RetrievalConfiguration(Base):
    """현재·대기 프리셋과 색인 버전을 단일 행으로 관리한다."""
    __tablename__ = "retrieval_configuration"

    # 서비스 전체가 공유하는 singleton이며 항상 id=1을 사용한다.
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
    # 재색인 중에는 문서 쓰기와 채팅을 막아 index version 혼합을 피한다.
    maintenance_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    active_preset = relationship("RetrievalPresetRecord", foreign_keys=[active_preset_key])
    pending_preset = relationship("RetrievalPresetRecord", foreign_keys=[pending_preset_key])
    active_search_algorithm = relationship("SearchAlgorithmRecord")


class ReindexJob(Base):
    """관리자가 요청한 프리셋 재색인 진행 상태를 기록한다."""
    __tablename__ = "reindex_jobs"
    __table_args__ = (
        Index("reindex_jobs_status_idx", "status", "created_at"),
        Index("reindex_jobs_requested_by_idx", "requested_by", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    requested_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    source_preset_key: Mapped[str] = mapped_column(Text, ForeignKey("retrieval_presets.key"), nullable=False)
    target_preset_key: Mapped[str] = mapped_column(Text, ForeignKey("retrieval_presets.key"), nullable=False)
    target_index_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default="pending")
    # 아래 flag는 즉시 전환과 전체 문서 재처리를 구분한다.
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
