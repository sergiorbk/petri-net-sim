"""Add has_custom_topology flag to sessions.

Revision ID: 016_add_session_custom_topology
Revises: 015_add_net_sharing
Create Date: 2026-04-29
"""

import sqlalchemy as sa
from alembic import op

revision = "016_add_session_custom_topology"
down_revision = "015_add_net_sharing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "has_custom_topology",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "has_custom_topology")
