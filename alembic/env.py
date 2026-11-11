"""Ambiente assíncrono do Alembic para PostgreSQL 18 com SQLAlchemy 2.0 e asyncpg."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.database import models  # noqa: F401 - garante registro de todos os modelos no Base.metadata
from src.database.base import Base
from src.database.config import DEFAULT_LOCAL_DATABASE_URL, DatabaseSettings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_database_url() -> str:
    fallback = config.get_main_option("sqlalchemy.url") or DEFAULT_LOCAL_DATABASE_URL
    settings = DatabaseSettings.from_env(default_url=fallback)
    return settings.database_url


def run_migrations_offline() -> None:
    """Executa migrações em modo offline gerando SQL sem abrir conexão."""
    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Executa migrações síncronas dentro de uma conexão assíncrona encapsulada."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Inicializa AsyncEngine (asyncpg) com NullPool e aplica migrações."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _resolve_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={
            "server_settings": {
                "timezone": "UTC",
                "application_name": "ferry-central-alembic",
            }
        },
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Executa migrações em modo online utilizando loop assíncrono."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

