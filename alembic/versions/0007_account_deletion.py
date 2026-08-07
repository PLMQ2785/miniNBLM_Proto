"""allow account deletion while preserving reindex audit history

Revision ID: 0007_account_deletion
Revises: 0006_admin_password_change
Create Date: 2026-08-06 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0007_account_deletion"
down_revision: str | None = "0006_admin_password_change"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("reindex_jobs_requested_by_fkey", "reindex_jobs", type_="foreignkey")
    op.alter_column("reindex_jobs", "requested_by", nullable=True)
    op.create_foreign_key(
        "reindex_jobs_requested_by_fkey",
        "reindex_jobs",
        "users",
        ["requested_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM reindex_jobs WHERE requested_by IS NULL")):
        raise RuntimeError("Cannot restore required reindex requesters after account deletion")
    op.drop_constraint("reindex_jobs_requested_by_fkey", "reindex_jobs", type_="foreignkey")
    op.alter_column("reindex_jobs", "requested_by", nullable=False)
    op.create_foreign_key(
        "reindex_jobs_requested_by_fkey",
        "reindex_jobs",
        "users",
        ["requested_by"],
        ["id"],
        ondelete="RESTRICT",
    )
