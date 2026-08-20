"""관리자에게 초기 비밀번호 변경을 요구한다.

Revision ID: 0006_admin_password_change
Revises: 0005_chat_session_history
Create Date: 2026-08-05 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0006_admin_password_change"
down_revision: str | None = "0005_chat_session_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """사용자에 비밀번호 변경 필요 상태를 추가한다."""
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute("UPDATE users SET must_change_password = true WHERE role = 'admin'")


def downgrade() -> None:
    """비밀번호 변경 필요 상태를 제거한다."""
    op.drop_column("users", "must_change_password")
