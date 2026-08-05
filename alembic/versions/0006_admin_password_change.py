"""require administrators to change bootstrap passwords

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
    op.drop_column("users", "must_change_password")
