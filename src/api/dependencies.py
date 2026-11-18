"""Dependências injetáveis do FastAPI para desacoplamento e testabilidade."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.config import ApiSettings
from src.api.service import FleetMetricsService
from src.database.repository import TelemetryRepository
from src.database.session import get_session_factory

_default_settings: ApiSettings | None = None


def get_api_settings() -> ApiSettings:
    """Retorna configurações da API REST a partir do ambiente."""
    global _default_settings
    if _default_settings is None:
        _default_settings = ApiSettings.from_env()
    return _default_settings


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Injeta uma AsyncSession com encerramento automático da transação."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_telemetry_repository(
    session: AsyncSession = Depends(get_db_session),
) -> TelemetryRepository:
    """Injeta uma instância de TelemetryRepository vinculada à sessão ativa."""
    return TelemetryRepository(session)


def get_fleet_service(
    repo: TelemetryRepository = Depends(get_telemetry_repository),
    settings: ApiSettings = Depends(get_api_settings),
) -> FleetMetricsService:
    """Injeta uma instância de FleetMetricsService."""
    return FleetMetricsService(repository=repo, settings=settings)
