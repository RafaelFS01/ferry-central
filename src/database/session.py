"""Gerenciamento de AsyncEngine e AsyncSession (SQLAlchemy 2.0 + asyncpg)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.database.config import DEFAULT_LOCAL_DATABASE_URL, DatabaseSettings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_async_db_engine(settings: DatabaseSettings | None = None) -> AsyncEngine:
    """Cria uma instância de AsyncEngine configurada para alta vazão com asyncpg."""
    cfg = settings or DatabaseSettings.from_env(default_url=DEFAULT_LOCAL_DATABASE_URL)

    return create_async_engine(
        cfg.database_url,
        echo=cfg.echo,
        pool_size=cfg.pool_size,
        max_overflow=cfg.max_overflow,
        pool_timeout=cfg.pool_timeout,
        pool_recycle=cfg.pool_recycle,
        pool_pre_ping=cfg.pool_pre_ping,
        connect_args={
            "command_timeout": cfg.command_timeout,
            "server_settings": {
                "timezone": "UTC",
                "application_name": "ferry-central",
            },
        },
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Cria uma fábrica de AsyncSession otimizada para operações assíncronas."""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


def get_engine() -> AsyncEngine:
    """Retorna o AsyncEngine singleton inicializado sob demanda."""
    global _engine
    if _engine is None:
        _engine = create_async_db_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Retorna o async_sessionmaker singleton vinculado ao AsyncEngine ativo."""
    global _session_factory
    if _session_factory is None:
        _session_factory = create_session_factory(get_engine())
    return _session_factory


@asynccontextmanager
async def get_async_session() -> AsyncIterator[AsyncSession]:
    """Fornece uma AsyncSession com commit/rollback automático por unidade de trabalho."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Encerra o pool de conexões assíncrono durante o graceful shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None

