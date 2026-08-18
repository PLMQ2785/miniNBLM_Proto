"""add per-user language model selection

Revision ID: 0009_user_llm
Revises: 0008_page_search_indexes
Create Date: 2026-08-11 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0009_user_llm"
down_revision: str | None = "0008_page_search_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("active_llm_endpoint_key", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "active_llm_endpoint_key")
