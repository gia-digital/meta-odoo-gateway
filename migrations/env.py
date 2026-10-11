"""Entorno de Alembic.

Desde la app, init_db() pasa su conexión en config.attributes["connection"]
(ya dentro de una transacción con advisory lock). Desde el CLI se abre una
conexión async con DATABASE_URL.
"""
import asyncio
from logging.config import fileConfig

from alembic import context
from pgvector.sqlalchemy import Vector
from sqlalchemy import pool
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.models import conversation, knowledge, runtime  # noqa: F401 registra las tablas
from app.models.db import Base

config = context.config
target_metadata = Base.metadata

# Sin esto, la reflexión ve `vector` como NullType y autogenerate no compara el tipo.
ischema_names["vector"] = Vector


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(get_settings().database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
elif (connection := config.attributes.get("connection")) is not None:
    do_run_migrations(connection)
else:
    if config.config_file_name is not None:
        fileConfig(config.config_file_name)
    asyncio.run(run_async_migrations())
