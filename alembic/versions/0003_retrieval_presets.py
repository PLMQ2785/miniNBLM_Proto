"""검색 프리셋과 재색인 작업 스키마를 추가한다.

Revision ID: 0003_retrieval_presets
Revises: 0002_user_auth_and_ownership
Create Date: 2026-08-04 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_retrieval_presets"
down_revision: str | None = "0002_user_auth_and_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PRESETS = (
    ("fine_grained", "Fine grained", 200, 40, 20),
    ("standard", "Standard", 500, 75, 12),
    ("balanced", "Balanced", 1000, 150, 8),
    ("broad_context", "Broad context", 2000, 300, 5),
    ("long_form", "Long form", 3500, 500, 4),
)


def upgrade() -> None:
    """검색 설정과 재색인 작업을 만들고 문서 인덱스 상태를 확장한다."""
    op.create_table(
        "retrieval_presets",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("chunk_size_chars", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap_chars", sa.Integer(), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("search_strategy", sa.Text(), nullable=False),
        sa.Column("distance_metric", sa.Text(), nullable=False),
        sa.Column("vector_index_type", sa.Text(), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("chunk_size_chars BETWEEN 200 AND 3500", name="retrieval_presets_chunk_size_check"),
        sa.CheckConstraint(
            "chunk_overlap_chars >= 0 AND chunk_overlap_chars <= chunk_size_chars / 2",
            name="retrieval_presets_overlap_check",
        ),
        sa.CheckConstraint("top_k BETWEEN 1 AND 20", name="retrieval_presets_top_k_check"),
    )
    presets_table = sa.table(
        "retrieval_presets",
        sa.column("key", sa.Text()),
        sa.column("display_name", sa.Text()),
        sa.column("chunk_size_chars", sa.Integer()),
        sa.column("chunk_overlap_chars", sa.Integer()),
        sa.column("top_k", sa.Integer()),
        sa.column("search_strategy", sa.Text()),
        sa.column("distance_metric", sa.Text()),
        sa.column("vector_index_type", sa.Text()),
    )
    op.bulk_insert(
        presets_table,
        [
            {
                "key": key,
                "display_name": display_name,
                "chunk_size_chars": chunk_size,
                "chunk_overlap_chars": overlap,
                "top_k": top_k,
                "search_strategy": "dense",
                "distance_metric": "cosine",
                "vector_index_type": "hnsw",
            }
            for key, display_name, chunk_size, overlap, top_k in PRESETS
        ],
    )

    op.create_table(
        "retrieval_configuration",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("active_preset_key", sa.Text(), nullable=False),
        sa.Column("pending_preset_key", sa.Text(), nullable=True),
        sa.Column("index_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("maintenance_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="retrieval_configuration_singleton_check"),
        sa.ForeignKeyConstraint(["active_preset_key"], ["retrieval_presets.key"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pending_preset_key"], ["retrieval_presets.key"], ondelete="RESTRICT"),
    )
    op.execute(
        """
        INSERT INTO retrieval_configuration
            (id, active_preset_key, index_version, maintenance_mode)
        VALUES (1, 'balanced', 1, false)
        """
    )

    op.add_column("documents", sa.Column("indexed_preset_key", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("index_version", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "documents_indexed_preset_key_fkey",
        "documents",
        "retrieval_presets",
        ["indexed_preset_key"],
        ["key"],
        ondelete="SET NULL",
    )
    op.execute("UPDATE documents SET indexed_preset_key = 'balanced', index_version = 1 WHERE status = 'indexed'")

    op.create_table(
        "reindex_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column("source_preset_key", sa.Text(), nullable=False),
        sa.Column("target_preset_key", sa.Text(), nullable=False),
        sa.Column("target_index_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("reindex_documents", sa.Boolean(), nullable=False),
        sa.Column("rebuild_vector_index", sa.Boolean(), nullable=False),
        sa.Column("runtime_settings_changed", sa.Boolean(), nullable=False),
        sa.Column("total_documents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_documents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_documents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'completed_with_errors', 'failed')",
            name="reindex_jobs_status_check",
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_preset_key"], ["retrieval_presets.key"]),
        sa.ForeignKeyConstraint(["target_preset_key"], ["retrieval_presets.key"]),
    )
    op.create_index("reindex_jobs_status_idx", "reindex_jobs", ["status", "created_at"])
    op.create_index("reindex_jobs_requested_by_idx", "reindex_jobs", ["requested_by", "created_at"])


def downgrade() -> None:
    """검색 프리셋과 재색인 작업 관련 스키마를 제거한다."""
    op.drop_index("reindex_jobs_requested_by_idx", table_name="reindex_jobs")
    op.drop_index("reindex_jobs_status_idx", table_name="reindex_jobs")
    op.drop_table("reindex_jobs")
    op.drop_constraint("documents_indexed_preset_key_fkey", "documents", type_="foreignkey")
    op.drop_column("documents", "index_version")
    op.drop_column("documents", "indexed_preset_key")
    op.drop_table("retrieval_configuration")
    op.drop_table("retrieval_presets")
