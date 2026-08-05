"""add chat session activity timestamp

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
    op.drop_index("chat_sessions_owner_updated_idx", table_name="chat_sessions")
    op.drop_column("chat_sessions", "updated_at")
