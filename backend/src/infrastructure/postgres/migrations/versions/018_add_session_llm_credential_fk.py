"""Link sessions to a BYOK credential profile.

Revision ID: 018_session_llm_fk
Revises: 017_user_llm_creds
Create Date: 2026-05-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "018_session_llm_fk"
down_revision: Union[str, None] = "017_user_llm_creds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "llm_credential_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_sessions_llm_credential_id",
        "sessions",
        "user_llm_credentials",
        ["llm_credential_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_sessions_llm_credential_id",
        "sessions",
        ["llm_credential_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_sessions_llm_credential_id", table_name="sessions")
    op.drop_constraint(
        "fk_sessions_llm_credential_id", "sessions", type_="foreignkey"
    )
    op.drop_column("sessions", "llm_credential_id")
