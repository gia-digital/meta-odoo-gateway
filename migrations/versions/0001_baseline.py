"""Esquema base: el que dejaba init_db() antes de Alembic.

Es idempotente porque las bases creadas antes de Alembic no tienen alembic_version:
en ellas solo crea las tablas, columnas, valores de enum e índices que falten
(bases de versiones viejas pueden no tener knowledge_products, runtime_settings, etc.).
Las migraciones siguientes ya NO necesitan ser idempotentes.

Revision ID: 0001
Revises:
Create Date: 2026-10-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENUMS = {
    "channel": ("whatsapp", "messenger", "instagram"),
    "conversationstatus": ("active", "qualified", "handed_off", "closed"),
    "qualificationsource": ("none", "meta_agent", "local_score", "chatwoot_agent"),
    "direction": ("inbound", "outbound"),
}


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _id() -> sa.Column:
    return sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True)


TABLES = {
    "conversations": lambda: (
        _id(),
        sa.Column("channel", _enum("channel"), nullable=False),
        sa.Column("external_user_id", sa.String(512), nullable=False),
        sa.Column("user_name", sa.String(255), nullable=True),
        sa.Column("user_phone", sa.String(64), nullable=True),
        sa.Column("user_email", sa.String(255), nullable=True),
        sa.Column("status", _enum("conversationstatus"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("score_breakdown", sa.JSON(), nullable=False),
        sa.Column("qualification_source", _enum("qualificationsource"), nullable=False),
        sa.Column("qualification_reason", sa.Text(), nullable=True),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handed_off_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("human_replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("product_interest", sa.String(255), nullable=True),
        sa.Column("lead_summary", sa.Text(), nullable=True),
        sa.Column("budget", sa.String(255), nullable=True),
        sa.Column("timeline", sa.String(255), nullable=True),
        sa.Column("preferred_contact_time", sa.String(255), nullable=True),
        sa.Column("odoo_lead_id", sa.Integer(), nullable=True),
        sa.Column("odoo_partner_id", sa.Integer(), nullable=True),
        _created_at(),
        _updated_at(),
    ),
    "messages": lambda: (
        _id(),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("direction", _enum("direction"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("external_message_id", sa.String(128), nullable=True),
        _created_at(),
    ),
    "knowledge_business": lambda: (
        _id(),
        sa.Column("business_description", sa.Text(), nullable=False),
        sa.Column("purchase_info", sa.Text(), nullable=False),
        sa.Column("payment_method", sa.Text(), nullable=False),
        sa.Column("delivery_and_shipping", sa.Text(), nullable=False),
        sa.Column("return_policy", sa.Text(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hours_of_operation", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("agent_instructions", sa.Text(), nullable=False),
        _updated_at(),
    ),
    "knowledge_faqs": lambda: (
        _id(),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        _created_at(),
        _updated_at(),
    ),
    "knowledge_products": lambda: (
        _id(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("aliases", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        _created_at(),
        _updated_at(),
    ),
    "knowledge_skills": lambda: (
        _id(),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("when_to_apply", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        _created_at(),
        _updated_at(),
    ),
    "knowledge_files": lambda: (
        _id(),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("stored_path", sa.String(512), nullable=False),
        sa.Column("mime", sa.String(128), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        _created_at(),
        _updated_at(),
    ),
    "knowledge_chunks": lambda: (
        _id(),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column(
            "file_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_files.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        _created_at(),
    ),
    "runtime_settings": lambda: (
        _id(),
        sa.Column("agent_model", sa.String(255), nullable=False),
        sa.Column("llm_provider", sa.String(32), nullable=False),
        sa.Column("openai_api_key", sa.Text(), nullable=False),
        sa.Column("anthropic_api_key", sa.Text(), nullable=False),
        sa.Column("openai_embedding_model", sa.String(255), nullable=False),
        sa.Column("debounce_seconds", sa.Float(), nullable=True),
        sa.Column("reply_max_bubbles", sa.Integer(), nullable=True),
        sa.Column("reply_bubble_delay_ms", sa.Integer(), nullable=True),
        sa.Column("reply_min_seconds", sa.Float(), nullable=True),
        sa.Column("reply_think_seconds", sa.Float(), nullable=True),
        sa.Column("reply_chars_per_sec", sa.Float(), nullable=True),
        sa.Column("reply_max_delay_seconds", sa.Float(), nullable=True),
        _updated_at(),
    ),
}

# Columnas que init_db() agregaba con ALTER a tablas ya existentes.
LEGACY_COLUMNS = {
    "conversations": (
        "qualification_source qualificationsource NOT NULL DEFAULT 'none'",
        "qualification_reason TEXT",
        "qualified_at TIMESTAMPTZ",
        "handed_off_at TIMESTAMPTZ",
        "human_replied_at TIMESTAMPTZ",
        "product_interest VARCHAR(255)",
        "lead_summary TEXT",
        "budget VARCHAR(255)",
        "timeline VARCHAR(255)",
        "preferred_contact_time VARCHAR(255)",
    ),
    "knowledge_business": ("agent_instructions TEXT NOT NULL DEFAULT ''",),
    "runtime_settings": (
        "llm_provider VARCHAR(32) NOT NULL DEFAULT ''",
        "debounce_seconds DOUBLE PRECISION",
        "reply_max_bubbles INTEGER",
        "reply_bubble_delay_ms INTEGER",
        "reply_min_seconds DOUBLE PRECISION",
        "reply_think_seconds DOUBLE PRECISION",
        "reply_chars_per_sec DOUBLE PRECISION",
        "reply_max_delay_seconds DOUBLE PRECISION",
    ),
}

INDEXES = (
    ("ix_conversations_channel", "conversations", "channel"),
    ("ix_conversations_external_user_id", "conversations", "external_user_id"),
    ("ix_conversations_odoo_lead_id", "conversations", "odoo_lead_id"),
    ("ix_conversations_qualification_source", "conversations", "qualification_source"),
    ("ix_conversations_status", "conversations", "status"),
    ("ix_messages_conversation_id", "messages", "conversation_id"),
    ("ix_messages_external_message_id", "messages", "external_message_id"),
    ("ix_knowledge_faqs_active", "knowledge_faqs", "active"),
    ("ix_knowledge_products_active", "knowledge_products", "active"),
    ("ix_knowledge_products_kind", "knowledge_products", "kind"),
    ("ix_knowledge_products_sort_order", "knowledge_products", "sort_order"),
    ("ix_knowledge_skills_active", "knowledge_skills", "active"),
    ("ix_knowledge_files_active", "knowledge_files", "active"),
    ("ix_knowledge_files_status", "knowledge_files", "status"),
    ("ix_knowledge_chunks_source_id", "knowledge_chunks", "source_id"),
    ("ix_knowledge_chunks_source_type", "knowledge_chunks", "source_type"),
)


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)
    op.execute("ALTER TYPE qualificationsource ADD VALUE IF NOT EXISTS 'chatwoot_agent'")

    existing = set(sa.inspect(bind).get_table_names())
    for table, columns in TABLES.items():
        if table not in existing:
            op.create_table(table, *columns())

    for table, columns in LEGACY_COLUMNS.items():
        for ddl in columns:
            op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {ddl}")

    # Instagram/Chatwoot source_id ~160+ chars (antes VARCHAR(128)).
    length = bind.execute(
        sa.text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'conversations' "
            "AND column_name = 'external_user_id'"
        )
    ).scalar()
    if length is not None and length < 512:
        op.execute("ALTER TABLE conversations ALTER COLUMN external_user_id TYPE VARCHAR(512)")

    for name, table, column in INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding "
        "ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    for table in reversed(list(TABLES)):
        op.drop_table(table)
    for name in ENUMS:
        op.execute(f"DROP TYPE IF EXISTS {name}")
