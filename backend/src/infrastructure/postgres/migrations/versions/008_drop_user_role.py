"""Drop role column from users table.

Role-based access (admin/user) removed — every user manages their own
API keys via the self-service REST API.

Revision ID: 008_drop_user_role
Revises: 007_add_session_title
Create Date: 2026-04-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_drop_user_role"
down_revision: Union[str, None] = "007_add_session_title"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("users", "role")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            server_default="user",
        ),
    )
