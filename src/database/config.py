"""Configuração da camada de banco de dados desacoplada de frameworks."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_LOCAL_DATABASE_URL = (
    "postgresql+asyncpg://ferry:ferry_local@localhost:5432/ferry_telemetry"
)


def normalize_async_database_url(raw_url: str) -> str:
    """Garante que a URL de conexão utilize o driver assíncrono asyncpg."""
    url = raw_url.strip()
    if not url:
        raise ValueError("DATABASE_URL não pode estar vazia.")

    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgresql+psycopg://"):
        return "postgresql+asyncpg://" + url[len("postgresql+psycopg://") :]
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql+asyncpg://" + url[len("postgresql+psycopg2://") :]
    return url


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Parâmetros de conexão e pool assíncrono para PostgreSQL."""

    database_url: str
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: float = 30.0
    pool_recycle: int = 1800
    pool_pre_ping: bool = True
    echo: bool = False
    command_timeout: float = 30.0

    @classmethod
    def from_env(cls, default_url: str | None = None) -> DatabaseSettings:
        """Carrega configurações a partir de variáveis de ambiente."""
        raw_url = os.getenv("DATABASE_URL") or default_url
        if not raw_url:
            raise ValueError(
                "Variável de ambiente DATABASE_URL não definida e nenhuma URL padrão informada."
            )

        return cls(
            database_url=normalize_async_database_url(raw_url),
            pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
            pool_timeout=float(os.getenv("DB_POOL_TIMEOUT", "30.0")),
            pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
            pool_pre_ping=_parse_bool(os.getenv("DB_POOL_PRE_PING"), True),
            echo=_parse_bool(os.getenv("DB_ECHO"), False),
            command_timeout=float(os.getenv("DB_COMMAND_TIMEOUT", "30.0")),
        )

