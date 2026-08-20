from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ChatSession(Base):
    """사용자 작업공간의 대화와 메시지를 묶으며 특정 문서 선택은 요구하지 않는다."""
    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index("chat_sessions_owner_idx", "owner_id", "created_at"),
        Index("chat_sessions_owner_updated_idx", "owner_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    # 과거 문서 귀속 세션과 호환하기 위한 선택 필드이며 새 작업공간 세션은 NULL이다.
    document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("documents.id"))
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    owner = relationship("User", back_populates="chat_sessions")
    document = relationship("Document", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    """대화 세션에 종속되어 발화와 검색 근거를 보관한다."""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chat_sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 전체 검색 Context ID와 실제 인용 source·trace는 서로 다른 감사 정보다.
    retrieved_chunk_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    message_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    session = relationship("ChatSession", back_populates="messages")
