"""사용자별 언어 모델 선택을 추가한다.

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
    """사용자에 활성 언어 모델 엔드포인트 선택을 추가한다."""
    op.add_column(
        "users",
        sa.Column("active_llm_endpoint_key", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """사용자별 언어 모델 선택을 제거한다."""
    op.drop_column("users", "active_llm_endpoint_key")
