"""Add users table

Revision ID: 002_add_users
Revises: 001_conversations_msgs
Create Date: 2025-01-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002_add_users"
down_revision: Union[str, None] = "001_conversations_msgs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("picture", sa.Text(), nullable=True),
        sa.Column("oauth_provider", sa.String(50), nullable=False),
        sa.Column("oauth_provider_id", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
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
        sa.UniqueConstraint("email"),
    )

    # Create indexes
    op.create_index("idx_users_email", "users", ["email"])
    op.create_index(
        "idx_users_oauth_provider",
        "users",
        ["oauth_provider", "oauth_provider_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_users_oauth_provider", table_name="users")
    op.drop_index("idx_users_email", table_name="users")
    op.drop_table("users")
