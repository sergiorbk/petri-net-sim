"""Add api_keys, sessions, and generated_files tables

Revision ID: 003_add_api_keys_sessions_files
Revises: 002_add_users
Create Date: 2026-04-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_add_api_keys_sessions_files"
down_revision: Union[str, None] = "002_add_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_USERS_FK = "users.id"


def upgrade() -> None:
    # --- api_keys ---
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("key_prefix", sa.String(8), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], [_USERS_FK], ondelete="CASCADE"),
    )
    op.create_index("idx_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)
    op.create_index("idx_api_keys_user_id", "api_keys", ["user_id"])

    # --- sessions ---
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("net_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_accessed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], [_USERS_FK], ondelete="CASCADE"),
    )
    op.create_index("idx_sessions_user_id", "sessions", ["user_id"])

    # --- generated_files ---
    op.create_table(
        "generated_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "content_type",
            sa.String(100),
            nullable=False,
            server_default="application/xml",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], [_USERS_FK], ondelete="CASCADE"),
    )
    op.create_index("idx_generated_files_session_id", "generated_files", ["session_id"])
    op.create_index("idx_generated_files_user_id", "generated_files", ["user_id"])
    op.create_index("idx_generated_files_expires_at", "generated_files", ["expires_at"])


def downgrade() -> None:
    op.drop_index("idx_generated_files_expires_at", table_name="generated_files")
    op.drop_index("idx_generated_files_user_id", table_name="generated_files")
    op.drop_index("idx_generated_files_session_id", table_name="generated_files")
    op.drop_table("generated_files")

    op.drop_index("idx_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("idx_api_keys_user_id", table_name="api_keys")
    op.drop_index("idx_api_keys_key_hash", table_name="api_keys")
    op.drop_table("api_keys")
