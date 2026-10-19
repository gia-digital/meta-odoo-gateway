"""Cierre de ciclo: resolved_at y id de conversación Chatwoot.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("chatwoot_conversation_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_conversations_chatwoot_conversation_id",
        "conversations",
        ["chatwoot_conversation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversations_chatwoot_conversation_id", table_name="conversations"
    )
    op.drop_column("conversations", "chatwoot_conversation_id")
    op.drop_column("conversations", "resolved_at")
