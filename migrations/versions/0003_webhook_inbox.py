"""Bandeja durable de webhooks Chatwoot e idempotencia de mensajes.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhook_inbox",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("dedupe_key", name="uq_webhook_inbox_dedupe_key"),
    )
    op.create_index(
        "ix_webhook_inbox_status_available",
        "webhook_inbox",
        ["status", "available_at"],
    )
    # Un mismo id de Chatwoot no puede generar dos filas de historial.
    op.execute(
        """
        DELETE FROM messages AS newer
        USING messages AS older
        WHERE newer.external_message_id IS NOT NULL
          AND newer.external_message_id = older.external_message_id
          AND newer.id > older.id
        """
    )
    op.create_index(
        "uq_messages_external_message_id",
        "messages",
        ["external_message_id"],
        unique=True,
        postgresql_where=sa.text("external_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_messages_external_message_id", table_name="messages")
    op.drop_index("ix_webhook_inbox_status_available", table_name="webhook_inbox")
    op.drop_table("webhook_inbox")
