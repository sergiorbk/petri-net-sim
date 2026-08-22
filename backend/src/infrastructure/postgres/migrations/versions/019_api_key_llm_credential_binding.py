"""Add llm_credential_id to api_keys for credential binding.

Revision ID: 019_api_key_llm_cred_binding
Revises: 018_session_llm_fk
Create Date: 2026-05-07
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "019_api_key_llm_cred_binding"
down_revision: Union[str, None] = "018_session_llm_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("llm_credential_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_api_keys_llm_credential_id",
        "api_keys",
        "user_llm_credentials",
        ["llm_credential_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_api_keys_llm_credential_id",
        "api_keys",
        ["llm_credential_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_api_keys_llm_credential_id", table_name="api_keys")
    op.drop_constraint(
        "fk_api_keys_llm_credential_id", "api_keys", type_="foreignkey"
    )
    op.drop_column("api_keys", "llm_credential_id")
