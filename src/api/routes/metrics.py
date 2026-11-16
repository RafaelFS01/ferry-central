"""Endpoints REST para consolidação e métricas operacionais da frota."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from src.api.dependencies import get_fleet_service
from src.api.schemas import FleetMetricsResponse
from src.api.service import FleetMetricsService

router = APIRouter(prefix="/api/v1/metrics", tags=["Metrics"])


@router.get(
    "/fleet",
    response_model=FleetMetricsResponse,
    status_code=status.HTTP_200_OK,
    summary="Sumário consolidado da frota náutica",
    description="Retorna status operacional das embarcações, velocidades médias e alertas ativos em tempo real.",
)
async def get_fleet_metrics(
    service: FleetMetricsService = Depends(get_fleet_service),
) -> FleetMetricsResponse:
    return await service.get_fleet_summary()
