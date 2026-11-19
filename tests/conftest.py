"""Fixtures compartilhadas para suíte de testes do Nó Central."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from src.database import (
    Base,
    DatabaseSettings,
    create_async_db_engine,
    create_session_factory,
)


@compiles(PG_UUID, "sqlite")
def _compile_pg_uuid_for_sqlite(type_: Any, compiler: Any, **kw: Any) -> str:
    """Permite compilar colunas PostgreSQL UUID em testes com SQLite em memória."""
    return "CHAR(32)"


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Cria e encerra AsyncEngine conectada ao PostgreSQL para testes."""
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL não definida para testes de integração PostgreSQL.")
    settings = DatabaseSettings.from_env()
    engine = create_async_db_engine(settings)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Fábrica de sessões assíncronas PostgreSQL para os testes."""
    return create_session_factory(db_engine)


@pytest.fixture
async def sqlite_engine() -> AsyncIterator[AsyncEngine]:
    """Cria AsyncEngine SQLite em memória (aiosqlite) com o schema completo do projeto."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def sqlite_session_factory(sqlite_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Fábrica de sessões assíncronas vinculada ao banco SQLite de teste."""
    return create_session_factory(sqlite_engine)
