"""Add petri_objects table for the built-in + user-custom subnet catalog

Revision ID: 011_add_petri_objects
Revises: 010_add_user_nets
Create Date: 2026-04-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "011_add_petri_objects"
down_revision: Union[str, None] = "010_add_user_nets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "petri_objects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "is_builtin",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("template_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("preview_svg", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "(is_builtin AND user_id IS NULL) OR (NOT is_builtin AND user_id IS NOT NULL)",
            name="ck_petri_objects_ownership",
        ),
    )

    # Fast listing of user's own objects.
    op.create_index(
        "ix_petri_objects_user_id",
        "petri_objects",
        ["user_id"],
    )

    # Partial unique indexes enforce case-insensitive uniqueness within each scope.
    op.execute(
        """
        CREATE UNIQUE INDEX ux_petri_objects_user_name
            ON petri_objects (user_id, lower(name))
            WHERE is_builtin = false
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_petri_objects_builtin_name
            ON petri_objects (lower(name))
            WHERE is_builtin = true
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_petri_objects_builtin_name")
    op.execute("DROP INDEX IF EXISTS ux_petri_objects_user_name")
    op.drop_index("ix_petri_objects_user_id", table_name="petri_objects")
    op.drop_table("petri_objects")
