"""Add user_nets table for user-owned mutable Petri net saves

Revision ID: 010_add_user_nets
Revises: 009_add_net_snapshots
Create Date: 2026-04-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010_add_user_nets"
down_revision: Union[str, None] = "009_add_net_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_nets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("net_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("origin_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["origin_snapshot_id"],
            ["net_snapshots.id"],
            ondelete="SET NULL",
        ),
    )

    op.create_index(
        "ix_user_nets_user_id",
        "user_nets",
        ["user_id"],
    )
    op.create_index(
        "ix_user_nets_user_id_updated_at",
        "user_nets",
        ["user_id", sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_user_nets_user_id_updated_at", table_name="user_nets")
    op.drop_index("ix_user_nets_user_id", table_name="user_nets")
    op.drop_table("user_nets")
