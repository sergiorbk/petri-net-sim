"""Remove Buffer built-in petri object

Revision ID: 021_remove_buffer_builtin
Revises: 020_seed_extra_petri_objects
Create Date: 2026-05-16
"""

from typing import Sequence, Union

from alembic import op

revision: str = "021_remove_buffer_builtin"
down_revision: Union[str, None] = "020_seed_extra_petri_objects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM petri_objects WHERE is_builtin = true AND lower(name) = 'buffer'"
    )


def downgrade() -> None:
    pass
