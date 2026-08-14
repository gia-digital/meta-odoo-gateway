"""Configuración SQLAlchemy async."""
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(
    settings.database_url,
    echo=settings.app_debug,
    pool_pre_ping=True,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def _ensure_qualification_columns(conn) -> None:
    """Añade columnas nuevas si la tabla ya existía (create_all no altera)."""
    await conn.execute(
        text(
            """
            DO $$ BEGIN
                CREATE TYPE qualificationsource AS ENUM (
                    'none', 'meta_agent', 'local_score', 'chatwoot_agent'
                );
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
            """
        )
    )
    # DBs creadas antes de chatwoot_agent
    await conn.execute(
        text(
            """
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_enum e
                    JOIN pg_type t ON e.enumtypid = t.oid
                    WHERE t.typname = 'qualificationsource'
                      AND e.enumlabel = 'chatwoot_agent'
                ) THEN
                    ALTER TYPE qualificationsource ADD VALUE 'chatwoot_agent';
                END IF;
            END $$;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE conversations
            ADD COLUMN IF NOT EXISTS qualification_source qualificationsource
                NOT NULL DEFAULT 'none';
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE conversations
            ADD COLUMN IF NOT EXISTS qualification_reason TEXT;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE conversations
            ADD COLUMN IF NOT EXISTS qualified_at TIMESTAMPTZ;
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_conversations_qualification_source
            ON conversations (qualification_source);
            """
        )
    )
    for col_sql in (
        "ADD COLUMN IF NOT EXISTS product_interest VARCHAR(255)",
        "ADD COLUMN IF NOT EXISTS lead_summary TEXT",
        "ADD COLUMN IF NOT EXISTS budget VARCHAR(255)",
        "ADD COLUMN IF NOT EXISTS timeline VARCHAR(255)",
        "ADD COLUMN IF NOT EXISTS preferred_contact_time VARCHAR(255)",
    ):
        await conn.execute(text(f"ALTER TABLE conversations {col_sql};"))


async def _ensure_knowledge_columns(conn) -> None:
    """Columnas nuevas en knowledge_business (create_all no altera tablas existentes)."""
    await conn.execute(
        text(
            """
            ALTER TABLE knowledge_business
            ADD COLUMN IF NOT EXISTS agent_instructions TEXT NOT NULL DEFAULT '';
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE runtime_settings
            ADD COLUMN IF NOT EXISTS llm_provider VARCHAR(32) NOT NULL DEFAULT '';
            """
        )
    )


async def _ensure_pgvector(conn) -> None:
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding
            ON knowledge_chunks
            USING hnsw (embedding vector_cosine_ops)
            """
        )
    )


async def init_db() -> None:
    """Crea las tablas. Para producción usar Alembic.

    Con varios workers de uvicorn, create_all puede chocar al crear ENUMs;
    reintentamos / ignoramos races de objetos ya existentes.
    """
    from app.models.conversation import Conversation, Message  # noqa: F401
    from app.models.knowledge import (  # noqa: F401
        KnowledgeBusiness,
        KnowledgeChunk,
        KnowledgeFaq,
        KnowledgeFile,
        KnowledgeProduct,
        KnowledgeSkill,
    )
    from app.models.runtime import RuntimeSettings  # noqa: F401

    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
            await _ensure_qualification_columns(conn)
            await _ensure_knowledge_columns(conn)
            try:
                await _ensure_pgvector(conn)
            except Exception as vec_exc:
                msg = str(vec_exc).lower()
                if "does not exist" not in msg and "already exists" not in msg:
                    raise
                logger.warning("pgvector_index_skipped", error=str(vec_exc))
    except Exception as exc:
        # Race típica con --workers > 1: el otro proceso ya creó el tipo/tabla
        msg = str(exc).lower()
        if "already exists" in msg or "duplicate" in msg:
            logger.warning("init_db_race_ignored", error=str(exc))
            async with engine.begin() as conn:
                try:
                    await _ensure_qualification_columns(conn)
                    await _ensure_knowledge_columns(conn)
                    try:
                        await _ensure_pgvector(conn)
                    except Exception as vec_exc:
                        vmsg = str(vec_exc).lower()
                        if "does not exist" not in vmsg and "already exists" not in vmsg:
                            raise
                        logger.warning("pgvector_index_skipped", error=str(vec_exc))
                except Exception as ensure_exc:
                    ensure_msg = str(ensure_exc).lower()
                    if "already exists" not in ensure_msg and "duplicate" not in ensure_msg:
                        raise
                    logger.warning("ensure_columns_race_ignored", error=str(ensure_exc))
        else:
            raise
