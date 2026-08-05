"""add user authentication and data ownership

Revision ID: 0002_user_auth_and_ownership
Revises: 0001_initial_schema
Create Date: 2026-08-04 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_user_auth_and_ownership"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("public_id", sa.Uuid(), nullable=False, server_default=sa.func.gen_random_uuid()),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('user', 'admin')", name="users_role_check"),
        sa.UniqueConstraint("public_id", name="users_public_id_key"),
        sa.UniqueConstraint("username", name="users_username_key"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="auth_sessions_token_hash_key"),
    )
    op.create_index("auth_sessions_user_idx", "auth_sessions", ["user_id"])

    op.add_column("documents", sa.Column("owner_id", sa.BigInteger(), nullable=True))
    op.add_column("chat_sessions", sa.Column("owner_id", sa.BigInteger(), nullable=True))

    connection = op.get_bind()
    document_count = connection.scalar(sa.text("SELECT count(*) FROM documents"))
    chat_count = connection.scalar(sa.text("SELECT count(*) FROM chat_sessions"))
    if document_count or chat_count:
        legacy_owner_id = connection.scalar(
            sa.text(
                """
                INSERT INTO users (username, password_hash, role, is_active)
                VALUES ('legacy_import', '!', 'user', false)
                RETURNING id
                """
            )
        )
        connection.execute(
            sa.text("UPDATE documents SET owner_id = :owner_id"),
            {"owner_id": legacy_owner_id},
        )
        connection.execute(
            sa.text(
                """
                UPDATE chat_sessions AS chat
                SET owner_id = document.owner_id
                FROM documents AS document
                WHERE chat.document_id = document.id
                """
            )
        )
        connection.execute(
            sa.text("UPDATE chat_sessions SET owner_id = :owner_id WHERE owner_id IS NULL"),
            {"owner_id": legacy_owner_id},
        )

    op.alter_column("documents", "owner_id", nullable=False)
    op.alter_column("chat_sessions", "owner_id", nullable=False)
    op.create_foreign_key(
        "documents_owner_id_fkey",
        "documents",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "chat_sessions_owner_id_fkey",
        "chat_sessions",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("documents_owner_idx", "documents", ["owner_id", "created_at"])
    op.create_index("chat_sessions_owner_idx", "chat_sessions", ["owner_id", "created_at"])


def downgrade() -> None:
    op.drop_index("chat_sessions_owner_idx", table_name="chat_sessions")
    op.drop_index("documents_owner_idx", table_name="documents")
    op.drop_constraint("chat_sessions_owner_id_fkey", "chat_sessions", type_="foreignkey")
    op.drop_constraint("documents_owner_id_fkey", "documents", type_="foreignkey")
    op.drop_column("chat_sessions", "owner_id")
    op.drop_column("documents", "owner_id")
    op.drop_index("auth_sessions_user_idx", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("users")
