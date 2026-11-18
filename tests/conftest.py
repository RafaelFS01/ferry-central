"""Fixtures compartilhadas para suíte de testes do Nó Central."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.database import (
    DatabaseSettings,
    create_async_db_engine,
    create_session_factory,
)


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
    """Fábrica de sessões assíncronas para os testes."""
    return create_session_factory(db_engine)
