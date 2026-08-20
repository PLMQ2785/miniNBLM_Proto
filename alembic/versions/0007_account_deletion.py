"""재색인 감사 이력을 보존하며 계정 삭제를 허용한다.

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
    """계정 삭제 시 재색인 요청자 참조를 비우도록 제약을 바꾼다."""
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
    """요청자가 없는 이력이 없을 때 필수 참조 제약을 복원한다."""
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
