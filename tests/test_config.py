"""Testes unitários de configuração da camada de banco de dados."""

from __future__ import annotations

import pytest

from src.database.config import DatabaseSettings, normalize_async_database_url


def test_normalize_async_database_url_converts_sync_schemes() -> None:
    assert (
        normalize_async_database_url("postgres://u:p@host:5432/db")
        == "postgresql+asyncpg://u:p@host:5432/db"
    )
    assert (
        normalize_async_database_url("postgresql://u:p@host:5432/db")
        == "postgresql+asyncpg://u:p@host:5432/db"
    )
    assert (
        normalize_async_database_url("postgresql+psycopg://u:p@host:5432/db")
        == "postgresql+asyncpg://u:p@host:5432/db"
    )
    assert (
        normalize_async_database_url("  postgresql+asyncpg://u:p@host:5432/db  ")
        == "postgresql+asyncpg://u:p@host:5432/db"
    )


def test_normalize_async_database_url_rejects_empty() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL"):
        normalize_async_database_url("   ")


def test_database_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://ferry:secret@db:5432/telemetria")
    monkeypatch.setenv("DB_POOL_SIZE", "16")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "32")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "15.5")
    monkeypatch.setenv("DB_POOL_RECYCLE", "900")
    monkeypatch.setenv("DB_POOL_PRE_PING", "false")
    monkeypatch.setenv("DB_ECHO", "true")
    monkeypatch.setenv("DB_COMMAND_TIMEOUT", "45.0")

    settings = DatabaseSettings.from_env()

    assert settings.database_url == "postgresql+asyncpg://ferry:secret@db:5432/telemetria"
    assert settings.pool_size == 16
    assert settings.max_overflow == 32
    assert settings.pool_timeout == 15.5
    assert settings.pool_recycle == 900
    assert settings.pool_pre_ping is False
    assert settings.echo is True
    assert settings.command_timeout == 45.0


def test_database_settings_requires_url_without_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        DatabaseSettings.from_env()

