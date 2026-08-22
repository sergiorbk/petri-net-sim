"""Add share_token and visibility to sessions for shareable chat links

Revision ID: 013_add_session_sharing
Revises: 012_seed_builtin_petri_objects
Create Date: 2026-04-26

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "013_add_session_sharing"
down_revision: Union[str, None] = "012_seed_builtin_petri_objects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # share_token: stable UUID used in public share URLs.
    # gen_random_uuid() populates existing rows; new rows get it from Python default.
    op.add_column(
        "sessions",
        sa.Column(
            "share_token",
            postgresql.UUID(as_uuid=True),
            nullable=True,  # temporarily nullable for backfill
        ),
    )
    op.execute("UPDATE sessions SET share_token = gen_random_uuid() WHERE share_token IS NULL")
    op.alter_column("sessions", "share_token", nullable=False)

    op.create_unique_constraint("uq_sessions_share_token", "sessions", ["share_token"])
    op.create_index("ix_sessions_share_token", "sessions", ["share_token"])

    # visibility: access control for the share link.
    op.add_column(
        "sessions",
        sa.Column(
            "visibility",
            sa.String(16),
            nullable=False,
            server_default="private",
        ),
    )
    # Index for public discovery listing (WHERE visibility = 'public').
    op.create_index(
        "ix_sessions_visibility",
        "sessions",
        ["visibility"],
        postgresql_where=sa.text("visibility = 'public'"),
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_visibility", table_name="sessions")
    op.drop_column("sessions", "visibility")
    op.drop_index("ix_sessions_share_token", table_name="sessions")
    op.drop_constraint("uq_sessions_share_token", "sessions", type_="unique")
    op.drop_column("sessions", "share_token")
