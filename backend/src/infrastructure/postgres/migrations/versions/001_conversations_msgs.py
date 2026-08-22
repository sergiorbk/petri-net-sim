"""Add conversations and messages tables

Revision ID: 001_conversations_msgs
Revises:
Create Date: 2025-01-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_conversations_msgs"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create conversations table
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
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
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for conversations
    op.create_index("idx_conversations_user_id", "conversations", ["user_id"])
    op.create_index("idx_conversations_status", "conversations", ["status"])
    op.create_index(
        "idx_conversations_user_status", "conversations", ["user_id", "status"]
    )

    # Create messages table
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "message_metadata", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("model_name", sa.String(255), nullable=True),
        sa.Column("tool_call_id", sa.String(255), nullable=True),
        sa.Column("tool_name", sa.String(255), nullable=True),
        sa.Column("tool_input", postgresql.JSONB(), nullable=True),
        sa.Column("tool_output", sa.Text(), nullable=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("parent_message_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_message_id"],
            ["messages.id"],
            ondelete="SET NULL",
        ),
    )

    # Create indexes for messages
    op.create_index("idx_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index(
        "idx_messages_conversation_sequence",
        "messages",
        ["conversation_id", "sequence_number"],
    )


def downgrade() -> None:
    # Drop messages table and indexes
    op.drop_index("idx_messages_conversation_sequence", table_name="messages")
    op.drop_index("idx_messages_conversation_id", table_name="messages")
    op.drop_table("messages")

    # Drop conversations table and indexes
    op.drop_index("idx_conversations_user_status", table_name="conversations")
    op.drop_index("idx_conversations_status", table_name="conversations")
    op.drop_index("idx_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
