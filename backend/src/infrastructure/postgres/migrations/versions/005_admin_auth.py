"""Replace OAuth auth with admin password auth.

Drop oauth_provider and oauth_provider_id columns.
Add password_hash and role columns.

Revision ID: 005_admin_auth
Revises: 004_drop_conversations_messages
Create Date: 2026-04-05

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_admin_auth"
down_revision: Union[str, None] = "004_drop_conversations_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop OAuth index and columns
    op.drop_index("idx_users_oauth_provider", table_name="users")
    op.drop_column("users", "oauth_provider_id")
    op.drop_column("users", "oauth_provider")

    # Add new columns
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            server_default="user",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "role")
    op.drop_column("users", "password_hash")

    op.add_column(
        "users",
        sa.Column("oauth_provider", sa.String(50), nullable=False, server_default="local"),
    )
    op.add_column(
        "users",
        sa.Column("oauth_provider_id", sa.String(255), nullable=False, server_default=""),
    )
    op.create_index(
        "idx_users_oauth_provider",
        "users",
        ["oauth_provider", "oauth_provider_id"],
        unique=True,
    )
