"""add page-level search indexes

Revision ID: 0008_page_search_indexes
Revises: 0007_account_deletion
Create Date: 2026-08-07 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op


revision: str = "0008_page_search_indexes"
down_revision: str | None = "0007_account_deletion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "document_pages_document_page_idx",
        "document_pages",
        ["document_id", "page_number"],
    )
    op.execute(
        "CREATE INDEX document_pages_text_fts_gin "
        "ON document_pages USING gin (to_tsvector('simple', text))"
    )
    op.execute(
        "CREATE INDEX document_pages_text_trgm_gist "
        "ON document_pages USING gist (text gist_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_index("document_pages_text_trgm_gist", table_name="document_pages")
    op.drop_index("document_pages_text_fts_gin", table_name="document_pages")
    op.drop_index("document_pages_document_page_idx", table_name="document_pages")
