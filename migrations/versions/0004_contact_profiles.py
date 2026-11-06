"""Perfil de contacto estable + empresa en conversaciones.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

channel_enum = postgresql.ENUM(
    "whatsapp", "messenger", "instagram", name="channel", create_type=False
)


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("user_company", sa.String(length=255), nullable=True),
    )
    op.create_table(
        "contact_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel", channel_enum, nullable=False),
        sa.Column("external_user_id", sa.String(length=512), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
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
        sa.UniqueConstraint(
            "channel",
            "external_user_id",
            name="uq_contact_profiles_channel_external",
        ),
    )
    op.create_index("ix_contact_profiles_channel", "contact_profiles", ["channel"])
    op.create_index(
        "ix_contact_profiles_external_user_id",
        "contact_profiles",
        ["external_user_id"],
    )
    # Semilla desde el ciclo más reciente de cada contacto.
    op.execute(
        """
        INSERT INTO contact_profiles (
            channel, external_user_id, display_name, company, phone, email
        )
        SELECT DISTINCT ON (channel, external_user_id)
            channel,
            external_user_id,
            user_name,
            user_company,
            user_phone,
            user_email
        FROM conversations
        ORDER BY channel, external_user_id, updated_at DESC NULLS LAST, id DESC
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_contact_profiles_external_user_id", table_name="contact_profiles"
    )
    op.drop_index("ix_contact_profiles_channel", table_name="contact_profiles")
    op.drop_table("contact_profiles")
    op.drop_column("conversations", "user_company")
