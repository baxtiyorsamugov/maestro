"""
Alembic-окружение Maestro.

URL базы берётся из config.load_database_settings() — тот же источник, что у бота
и админки, чтобы миграции никогда не уехали на другую базу, чем приложение.
"""
import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database as db
from config import load_database_settings

config = context.config

# URL по умолчанию берём из .env — тот же источник, что у бота и админки.
# Если вызывающий код задал url явно (тесты, скрипты), его не перетираем.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", load_database_settings().url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = db.Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite не умеет ALTER — без batch-режима правки колонок падают.
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
