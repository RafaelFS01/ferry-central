"""Endpoints de compatibilidade direta com o frontend Next.js (/api/telemetry/*)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.dependencies import get_telemetry_repository
from src.api.schemas import TelemetryResponse
from src.database.repository import TelemetryRepository

router = APIRouter(prefix="/api/telemetry", tags=["Compatibility"])


@router.get(
    "/latest",
    response_model=TelemetryResponse,
    status_code=status.HTTP_200_OK,
    summary="Última telemetria para o frontend do Dashboard",
)
async def get_latest_compat(
    boat_id: str | None = Query(default=None, description="Identificador opcional da embarcação"),
    repo: TelemetryRepository = Depends(get_telemetry_repository),
) -> TelemetryResponse:
    if boat_id:
        record = await repo.get_latest_by_boat(boat_id)
    else:
        record = await repo.get_latest_global()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhuma telemetria disponível na base.",
        )
    return TelemetryResponse.model_validate(record)


@router.get(
    "/history",
    response_model=list[TelemetryResponse],
    status_code=status.HTTP_200_OK,
    summary="Histórico de telemetria em formato lista para o frontend do Dashboard",
)
async def get_history_compat(
    limit: int = Query(default=100, ge=1, le=1000),
    boat_id: str | None = Query(default=None),
    repo: TelemetryRepository = Depends(get_telemetry_repository),
) -> list[TelemetryResponse]:
    if boat_id:
        records = await repo.get_history_by_boat(boat_id=boat_id, limit=limit, order_asc=True)
    else:
        records = await repo.get_history_global(limit=limit)
    return [TelemetryResponse.model_validate(r) for r in records]
