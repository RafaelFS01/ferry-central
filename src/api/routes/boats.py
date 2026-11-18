"""Endpoints REST para consulta de telemetrias individuais e séries temporais de embarcações."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.dependencies import get_telemetry_repository
from src.api.schemas import HistoryPaginationResponse, TelemetryResponse
from src.database.repository import TelemetryRepository

router = APIRouter(prefix="/api/v1/boats", tags=["Boats"])


def _parse_query_datetime(val: str | None, param_name: str) -> datetime | None:
    if val is None:
        return None
    raw = val.strip()
    if not raw:
        return None
    if " " in raw and "+" not in raw:
        parts = raw.rsplit(" ", 1)
        if len(parts) == 2 and (":" in parts[1] or parts[1].isdigit()):
            raw = f"{parts[0]}+{parts[1]}"
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Parâmetro '{param_name}' com formato de data inválido: {val!r}. Use ISO 8601.",
        ) from exc


@router.get(
    "/{boat_id}/latest",
    response_model=TelemetryResponse,
    status_code=status.HTTP_200_OK,
    summary="Retorna o pacote de telemetria mais recente da embarcação",
    description="Consulta o registro mais recente gravado para o boat_id especificado. Retorna 404 caso não haja registros.",
)
async def get_boat_latest_telemetry(
    boat_id: str,
    repo: TelemetryRepository = Depends(get_telemetry_repository),
) -> TelemetryResponse:
    latest = await repo.get_latest_by_boat(boat_id)
    if latest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhuma telemetria encontrada para a embarcação '{boat_id}'.",
        )
    return TelemetryResponse.model_validate(latest)


@router.get(
    "/{boat_id}/history",
    response_model=HistoryPaginationResponse,
    status_code=status.HTTP_200_OK,
    summary="Retorna série temporal de telemetrias com paginação para traçado de rotas",
    description="Recupera histórico paginado ordenado temporalmente, permitindo filtros de intervalo por 'from' e 'to'.",
)
async def get_boat_telemetry_history(
    boat_id: str,
    from_time: str | None = Query(
        default=None,
        alias="from",
        description="Timestamp inicial UTC (formato ISO 8601)",
    ),
    to_time: str | None = Query(
        default=None,
        alias="to",
        description="Timestamp final UTC (formato ISO 8601)",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Quantidade máxima de registros retornados (padrão 100, máx 1000)",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Deslocamento para paginação (padrão 0)",
    ),
    order: Literal["asc", "desc"] = Query(
        default="asc",
        description="Ordem temporal dos registros: 'asc' para traçar rotas cronológicas ou 'desc' para mais recentes primeiro",
    ),
    repo: TelemetryRepository = Depends(get_telemetry_repository),
) -> HistoryPaginationResponse:
    parsed_from = _parse_query_datetime(from_time, "from")
    parsed_to = _parse_query_datetime(to_time, "to")

    if parsed_from and parsed_to and parsed_from > parsed_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parâmetro 'from' não pode ser posterior a 'to'.",
        )

    total = await repo.count_history_by_boat(
        boat_id=boat_id,
        from_time=parsed_from,
        to_time=parsed_to,
    )

    records = await repo.get_history_by_boat(
        boat_id=boat_id,
        limit=limit,
        offset=offset,
        from_time=parsed_from,
        to_time=parsed_to,
        order_asc=(order == "asc"),
    )

    items = [TelemetryResponse.model_validate(r) for r in records]

    return HistoryPaginationResponse(
        boat_id=boat_id,
        total=total,
        limit=limit,
        offset=offset,
        items=items,
    )
