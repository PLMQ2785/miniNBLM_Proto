"""대화 세션에 최근 활동 시각을 추가한다.

Revision ID: 0005_chat_session_history
Revises: 0004_search_algorithms
Create Date: 2026-08-05 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005_chat_session_history"
down_revision: str | None = "0004_search_algorithms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """기존 대화 시각을 보정하고 사용자별 최근 활동 인덱스를 만든다."""
    op.add_column(
        "chat_sessions",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE chat_sessions SET updated_at = created_at")
    op.alter_column(
        "chat_sessions",
        "updated_at",
        nullable=False,
        server_default=sa.func.now(),
    )
    op.create_index(
        "chat_sessions_owner_updated_idx",
        "chat_sessions",
        ["owner_id", "updated_at"],
    )


def downgrade() -> None:
    """최근 활동 인덱스와 시각 열을 제거한다."""
    op.drop_index("chat_sessions_owner_updated_idx", table_name="chat_sessions")
    op.drop_column("chat_sessions", "updated_at")
