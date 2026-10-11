"""Configuración SQLAlchemy async."""
import asyncio
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
# Clave arbitraria de pg_advisory_xact_lock: serializa migraciones entre procesos.
MIGRATIONS_LOCK_ID = 727_100_001


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


def _upgrade_schema(connection: Connection) -> None:
    from alembic import command
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from alembic.util import CommandError

    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["connection"] = connection
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    current = MigrationContext.configure(connection).get_current_revision()

    if current == head:
        return
    if current is not None:
        try:
            script.get_revision(current)
        except CommandError:
            # Rollback a una imagen anterior: la base ya va adelante. Las migraciones
            # deben ser compatibles hacia atrás (solo agregar), así que se sigue sin migrar.
            logger.warning("db_schema_newer_than_code", db_revision=current, code_head=head)
            return

    logger.info("db_migrating", from_revision=current, to_revision=head)
    command.upgrade(cfg, "head")


async def init_db() -> None:
    """Aplica las migraciones de Alembic pendientes (equivale a `alembic upgrade head`)."""
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": MIGRATIONS_LOCK_ID})
        await conn.run_sync(_upgrade_schema)
