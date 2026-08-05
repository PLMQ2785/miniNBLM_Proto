"""separate search algorithms from chunking presets

Revision ID: 0004_search_algorithms
Revises: 0003_retrieval_presets
Create Date: 2026-08-04 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_search_algorithms"
down_revision: str | None = "0003_retrieval_presets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ALGORITHMS = (
    (
        "dense",
        "의미 검색",
        "BGE-M3 embedding과 cosine 유사도로 표현이 다른 관련 문장을 찾습니다.",
    ),
    (
        "keyword",
        "키워드 검색",
        "PostgreSQL FTS로 질문에 포함된 용어가 직접 등장하는 청크를 찾습니다.",
    ),
    (
        "substring",
        "부분 문자열 검색",
        "pg_trgm으로 약어, 영문 용어, 일부만 입력한 문자열과 유사한 청크를 찾습니다.",
    ),
    (
        "hybrid",
        "하이브리드 RRF",
        "의미·키워드·부분 문자열 검색 순위를 RRF로 합쳐 일반적인 질문에 대응합니다.",
    ),
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "search_algorithms",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    algorithms_table = sa.table(
        "search_algorithms",
        sa.column("key", sa.Text()),
        sa.column("display_name", sa.Text()),
        sa.column("description", sa.Text()),
    )
    op.bulk_insert(
        algorithms_table,
        [
            {"key": key, "display_name": display_name, "description": description}
            for key, display_name, description in ALGORITHMS
        ],
    )
    op.add_column(
        "retrieval_configuration",
        sa.Column("active_search_algorithm_key", sa.Text(), nullable=False, server_default="dense"),
    )
    op.create_foreign_key(
        "retrieval_configuration_search_algorithm_fkey",
        "retrieval_configuration",
        "search_algorithms",
        ["active_search_algorithm_key"],
        ["key"],
        ondelete="RESTRICT",
    )
    op.drop_column("retrieval_presets", "vector_index_type")
    op.drop_column("retrieval_presets", "distance_metric")
    op.drop_column("retrieval_presets", "search_strategy")
    op.execute(
        "CREATE INDEX chunks_content_fts_gin "
        "ON chunks USING gin (to_tsvector('simple', content))"
    )
    op.execute(
        "CREATE INDEX chunks_content_trgm_gist "
        "ON chunks USING gist (content gist_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_index("chunks_content_trgm_gist", table_name="chunks")
    op.drop_index("chunks_content_fts_gin", table_name="chunks")
    op.add_column(
        "retrieval_presets",
        sa.Column("search_strategy", sa.Text(), nullable=False, server_default="dense"),
    )
    op.add_column(
        "retrieval_presets",
        sa.Column("distance_metric", sa.Text(), nullable=False, server_default="cosine"),
    )
    op.add_column(
        "retrieval_presets",
        sa.Column("vector_index_type", sa.Text(), nullable=False, server_default="hnsw"),
    )
    op.drop_constraint(
        "retrieval_configuration_search_algorithm_fkey",
        "retrieval_configuration",
        type_="foreignkey",
    )
    op.drop_column("retrieval_configuration", "active_search_algorithm_key")
    op.drop_table("search_algorithms")
