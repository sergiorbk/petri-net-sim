"""Add title column to sessions table.

Revision ID: 007_add_session_title
Revises: 006_add_oauth_provider
Create Date: 2026-04-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_add_session_title"
down_revision: Union[str, None] = "006_add_oauth_provider"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("title", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "title")
