"""Re-add OAuth provider columns (nullable) for social login support.

Revision ID: 006_add_oauth_provider
Revises: 005_admin_auth
Create Date: 2026-04-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_add_oauth_provider"
down_revision: Union[str, None] = "005_admin_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auth_provider", sa.String(50), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("auth_provider_id", sa.String(255), nullable=True),
    )
    op.create_index(
        "idx_users_oauth_provider",
        "users",
        ["auth_provider", "auth_provider_id"],
        unique=True,
        postgresql_where=sa.text("auth_provider IS NOT NULL AND auth_provider_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_users_oauth_provider", table_name="users")
    op.drop_column("users", "auth_provider_id")
    op.drop_column("users", "auth_provider")
