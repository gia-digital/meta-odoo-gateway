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
                CREATE TYPE qualificationsource AS ENUM ('none', 'meta_agent', 'local_score');
            EXCEPTION
                WHEN duplicate_object THEN null;
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


async def init_db() -> None:
    """Crea las tablas. Para producción usar Alembic.

    Con varios workers de uvicorn, create_all puede chocar al crear ENUMs;
    reintentamos / ignoramos races de objetos ya existentes.
    """
    from app.models.conversation import Conversation, Message  # noqa: F401

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _ensure_qualification_columns(conn)
    except Exception as exc:
        # Race típica con --workers > 1: el otro proceso ya creó el tipo/tabla
        msg = str(exc).lower()
        if "already exists" in msg or "duplicate" in msg:
            logger.warning("init_db_race_ignored", error=str(exc))
            async with engine.begin() as conn:
                try:
                    await _ensure_qualification_columns(conn)
                except Exception as ensure_exc:
                    ensure_msg = str(ensure_exc).lower()
                    if "already exists" not in ensure_msg and "duplicate" not in ensure_msg:
                        raise
                    logger.warning("ensure_columns_race_ignored", error=str(ensure_exc))
        else:
            raise
