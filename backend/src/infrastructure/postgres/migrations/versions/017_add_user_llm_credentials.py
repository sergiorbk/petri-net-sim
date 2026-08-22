"""Add user_llm_credentials table for BYOK profiles.

Revision ID: 017_user_llm_creds
Revises: 016_add_session_custom_topology
Create Date: 2026-05-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "017_user_llm_creds"
down_revision: Union[str, None] = "016_add_session_custom_topology"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_llm_credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        # Ollama profiles may have no key — column is nullable.
        sa.Column("encrypted_api_key", sa.LargeBinary(), nullable=True),
        sa.Column("cipher_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "provider IN ('openai', 'anthropic', 'ollama')",
            name="ck_user_llm_credentials_provider",
        ),
    )

    # Active-name uniqueness scoped to one user; soft-deleted rows do not
    # collide with a re-created profile of the same name.
    op.create_index(
        "uq_user_llm_credentials_user_name_active",
        "user_llm_credentials",
        ["user_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_user_llm_credentials_user_id",
        "user_llm_credentials",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_user_llm_credentials_user_id", table_name="user_llm_credentials"
    )
    op.drop_index(
        "uq_user_llm_credentials_user_name_active",
        table_name="user_llm_credentials",
    )
    op.drop_table("user_llm_credentials")
