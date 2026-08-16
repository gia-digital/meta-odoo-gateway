"""Configuración SQLAlchemy async."""
import asyncio
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def is_deadlock(exc: BaseException) -> bool:
    text_exc = str(exc).lower()
    return "deadlock" in text_exc or "deadlockdetected" in text_exc


async def commit_with_retry(session: AsyncSession, *, attempts: int = 3) -> None:
    """Reintenta commit ante deadlock de Postgres (p. ej. DDL de arranque)."""
    delay = 0.15
    last: BaseException | None = None
    for i in range(attempts):
        try:
            await session.commit()
            return
        except Exception as exc:
            last = exc
            await session.rollback()
            if not is_deadlock(exc) or i == attempts - 1:
                raise
            logger.warning("db_deadlock_retry", attempt=i + 1, error=str(exc))
            await asyncio.sleep(delay)
            delay *= 2
    if last:
        raise last


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


async def _column_exists(conn, table: str, column: str) -> bool:
    result = await conn.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table
              AND column_name = :column
            """
        ),
        {"table": table, "column": column},
    )
    return result.scalar() is not None


async def _index_exists(conn, name: str) -> bool:
    result = await conn.execute(
        text(
            """
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = 'public' AND indexname = :name
            """
        ),
        {"name": name},
    )
    return result.scalar() is not None


async def _add_column_if_missing(conn, table: str, column: str, ddl: str) -> None:
    """Evita ALTER (AccessExclusiveLock) si la columna ya existe."""
    if await _column_exists(conn, table, column):
        return
    await conn.execute(text(f"ALTER TABLE {table} {ddl}"))
    logger.info("schema_column_added", table=table, column=column)


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
    for column, ddl in (
        (
            "qualification_source",
            "ADD COLUMN qualification_source qualificationsource NOT NULL DEFAULT 'none'",
        ),
        ("qualification_reason", "ADD COLUMN qualification_reason TEXT"),
        ("qualified_at", "ADD COLUMN qualified_at TIMESTAMPTZ"),
        ("handed_off_at", "ADD COLUMN handed_off_at TIMESTAMPTZ"),
        ("human_replied_at", "ADD COLUMN human_replied_at TIMESTAMPTZ"),
        ("product_interest", "ADD COLUMN product_interest VARCHAR(255)"),
        ("lead_summary", "ADD COLUMN lead_summary TEXT"),
        ("budget", "ADD COLUMN budget VARCHAR(255)"),
        ("timeline", "ADD COLUMN timeline VARCHAR(255)"),
        ("preferred_contact_time", "ADD COLUMN preferred_contact_time VARCHAR(255)"),
    ):
        await _add_column_if_missing(conn, "conversations", column, ddl)

    if not await _index_exists(conn, "ix_conversations_qualification_source"):
        await conn.execute(
            text(
                """
                CREATE INDEX ix_conversations_qualification_source
                ON conversations (qualification_source)
                """
            )
        )


async def _ensure_knowledge_columns(conn) -> None:
    """Columnas nuevas en knowledge_business (create_all no altera tablas existentes)."""
    await _add_column_if_missing(
        conn,
        "knowledge_business",
        "agent_instructions",
        "ADD COLUMN agent_instructions TEXT NOT NULL DEFAULT ''",
    )
    await _add_column_if_missing(
        conn,
        "runtime_settings",
        "llm_provider",
        "ADD COLUMN llm_provider VARCHAR(32) NOT NULL DEFAULT ''",
    )
    for column, ddl in (
        ("debounce_seconds", "ADD COLUMN debounce_seconds DOUBLE PRECISION"),
        ("reply_max_bubbles", "ADD COLUMN reply_max_bubbles INTEGER"),
        ("reply_bubble_delay_ms", "ADD COLUMN reply_bubble_delay_ms INTEGER"),
        ("reply_min_seconds", "ADD COLUMN reply_min_seconds DOUBLE PRECISION"),
        ("reply_think_seconds", "ADD COLUMN reply_think_seconds DOUBLE PRECISION"),
        ("reply_chars_per_sec", "ADD COLUMN reply_chars_per_sec DOUBLE PRECISION"),
        ("reply_max_delay_seconds", "ADD COLUMN reply_max_delay_seconds DOUBLE PRECISION"),
    ):
        await _add_column_if_missing(conn, "runtime_settings", column, ddl)


async def _ensure_pgvector(conn) -> None:
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    if await _index_exists(conn, "ix_knowledge_chunks_embedding"):
        return
    await conn.execute(
        text(
            """
            CREATE INDEX ix_knowledge_chunks_embedding
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
