"""Add share_token and visibility to user_nets.

Revision ID: 015_add_net_sharing
Revises: 014_add_session_messages
Create Date: 2026-04-27
"""

import sqlalchemy as sa
from alembic import op

revision = "015_add_net_sharing"
down_revision = "014_add_session_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_nets",
        sa.Column(
            "share_token",
            sa.dialects.postgresql.UUID(as_uuid=False),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.create_unique_constraint("uq_user_nets_share_token", "user_nets", ["share_token"])
    op.create_index("ix_user_nets_share_token", "user_nets", ["share_token"])
    op.add_column(
        "user_nets",
        sa.Column(
            "visibility",
            sa.String(16),
            nullable=False,
            server_default="private",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_nets", "visibility")
    op.drop_index("ix_user_nets_share_token", table_name="user_nets")
    op.drop_constraint("uq_user_nets_share_token", "user_nets", type_="unique")
    op.drop_column("user_nets", "share_token")
