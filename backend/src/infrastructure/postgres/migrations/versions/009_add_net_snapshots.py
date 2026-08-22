"""Add net_snapshots table for versioned Petri net history

Revision ID: 009_add_net_snapshots
Revises: 008_drop_user_role
Create Date: 2026-04-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009_add_net_snapshots"
down_revision: Union[str, None] = "008_drop_user_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "net_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "session_id",
            sa.String(64),
            nullable=False,
        ),
        sa.Column("net_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "source",
            sa.String(16),
            nullable=False,
            server_default="agent",
        ),
        sa.Column(
            "parent_snapshot_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_snapshot_id"],
            ["net_snapshots.id"],
            ondelete="SET NULL",
        ),
    )

    # Unique deduplication index: same net in the same session → one row
    op.create_index(
        "idx_net_snapshots_session_content",
        "net_snapshots",
        ["session_id", "content_hash"],
        unique=True,
    )
    # Fast listing of all snapshots for a session (version history UI)
    op.create_index(
        "idx_net_snapshots_session_id",
        "net_snapshots",
        ["session_id"],
    )
    # Ownership check in simulate endpoint: WHERE id=$1 AND session_id=$2
    op.create_index(
        "idx_net_snapshots_id_session",
        "net_snapshots",
        ["id", "session_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_net_snapshots_id_session", table_name="net_snapshots")
    op.drop_index("idx_net_snapshots_session_id", table_name="net_snapshots")
    op.drop_index("idx_net_snapshots_session_content", table_name="net_snapshots")
    op.drop_table("net_snapshots")
