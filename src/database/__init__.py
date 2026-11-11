"""Camada de persistência assíncrona baseada em SQLAlchemy 2.0 e asyncpg."""

from src.database.base import Base, POSTGRES_NAMING_CONVENTION
from src.database.config import (
    DEFAULT_LOCAL_DATABASE_URL,
    DatabaseSettings,
    normalize_async_database_url,
)
from src.database.models import Telemetry
from src.database.repository import (
    DEFAULT_BATCH_CHUNK_SIZE,
    TelemetryRecordInput,
    TelemetryRepository,
    ensure_utc_datetime,
)
from src.database.session import (
    create_async_db_engine,
    create_session_factory,
    dispose_engine,
    get_async_session,
    get_engine,
    get_session_factory,
)

__all__ = [
    "Base",
    "DEFAULT_BATCH_CHUNK_SIZE",
    "DEFAULT_LOCAL_DATABASE_URL",
    "DatabaseSettings",
    "POSTGRES_NAMING_CONVENTION",
    "Telemetry",
    "TelemetryRecordInput",
    "TelemetryRepository",
    "create_async_db_engine",
    "create_session_factory",
    "dispose_engine",
    "ensure_utc_datetime",
    "get_async_session",
    "get_engine",
    "get_session_factory",
    "normalize_async_database_url",
]

