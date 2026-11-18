"""Repositório assíncrono de telemetria desacoplado de frameworks externos."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Telemetry

# Asyncpg limita a 32.767 parâmetros por comando SQL; com 16 colunas por linha,
# lotes de 1.000 linhas (16.000 parâmetros) mantêm margem segura e alta vazão.
DEFAULT_BATCH_CHUNK_SIZE = 1000


def ensure_utc_datetime(value: datetime) -> datetime:
    """Normaliza timestamps para UTC timezone-aware."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class TelemetryRecordInput:
    """DTO de entrada desacoplado para ingestão de pacotes na tabela telemetria."""

    packet_id: UUID
    boat_id: str
    sequence_number: int
    timestamp: datetime
    latitude: float
    longitude: float
    speed_knots: float | None = None
    course_heading: float | None = None
    hdop: float | None = None
    satellites_tracked: int | None = None
    engine_rpm: float | None = None
    engine_temp_celsius: float | None = None
    fuel_level_percent: float | None = None
    battery_voltage: float | None = None
    network_latency_ms: float | None = None
    network_rssi_dbm: int | None = None

    def to_row(self) -> dict[str, Any]:
        """Converte o DTO em dicionário pronto para INSERT no PostgreSQL."""
        row = asdict(self)
        row["timestamp"] = ensure_utc_datetime(self.timestamp)
        return row


def _normalize_record(record: TelemetryRecordInput | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(record, TelemetryRecordInput):
        return record.to_row()
    row = dict(record)
    ts = row.get("timestamp")
    if isinstance(ts, datetime):
        row["timestamp"] = ensure_utc_datetime(ts)
    return row


class TelemetryRepository:
    """Camada de acesso a dados assíncrona para escrita idempotente e consultas."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_packet(
        self,
        record: TelemetryRecordInput | Mapping[str, Any],
    ) -> bool:
        """Insere um pacote de forma idempotente (ON CONFLICT DO NOTHING).

        Retorna True se o pacote foi inserido pela primeira vez ou False se já existia.
        """
        payload = _normalize_record(record)
        stmt = (
            pg_insert(Telemetry)
            .values(**payload)
            .on_conflict_do_nothing(index_elements=[Telemetry.packet_id])
            .returning(Telemetry.packet_id)
        )
        inserted_id = await self._session.scalar(stmt)
        return inserted_id is not None

    async def insert_batch(
        self,
        records: Sequence[TelemetryRecordInput | Mapping[str, Any]],
        chunk_size: int = DEFAULT_BATCH_CHUNK_SIZE,
    ) -> int:
        """Persiste pacotes em lote com idempotência por packet_id.

        Retorna a quantidade total de novos registros efetivamente gravados.
        """
        if not records:
            return 0
        if chunk_size <= 0:
            raise ValueError("chunk_size deve ser maior que zero.")

        inserted_total = 0
        for start in range(0, len(records), chunk_size):
            chunk = [_normalize_record(item) for item in records[start : start + chunk_size]]
            stmt = (
                pg_insert(Telemetry)
                .values(chunk)
                .on_conflict_do_nothing(index_elements=[Telemetry.packet_id])
                .returning(Telemetry.packet_id)
            )
            result = await self._session.scalars(stmt)
            inserted_total += len(result.all())
        return inserted_total

    async def exists_packet(self, packet_id: UUID) -> bool:
        """Verifica se um packet_id já foi persistido."""
        stmt = select(Telemetry.packet_id).where(Telemetry.packet_id == packet_id).limit(1)
        return (await self._session.scalar(stmt)) is not None

    async def get_by_packet_id(self, packet_id: UUID) -> Telemetry | None:
        """Busca um registro pelo seu identificador único packet_id."""
        stmt = select(Telemetry).where(Telemetry.packet_id == packet_id)
        return await self._session.scalar(stmt)

    async def get_latest_by_boat(self, boat_id: str) -> Telemetry | None:
        """Retorna a telemetria mais recente da embarcação usando idx_telemetria_boat_timestamp."""
        stmt = (
            select(Telemetry)
            .where(Telemetry.boat_id == boat_id)
            .order_by(Telemetry.timestamp.desc())
            .limit(1)
        )
        return await self._session.scalar(stmt)

    async def get_history_by_boat(
        self,
        boat_id: str,
        limit: int = 100,
        offset: int = 0,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        order_asc: bool = False,
    ) -> list[Telemetry]:
        """Retorna histórico paginado para a embarcação com suporte a intervalo temporal."""
        stmt = select(Telemetry).where(Telemetry.boat_id == boat_id)
        if from_time is not None:
            stmt = stmt.where(Telemetry.timestamp >= ensure_utc_datetime(from_time))
        if to_time is not None:
            stmt = stmt.where(Telemetry.timestamp <= ensure_utc_datetime(to_time))

        if order_asc:
            stmt = stmt.order_by(Telemetry.timestamp.asc())
        else:
            stmt = stmt.order_by(Telemetry.timestamp.desc())

        stmt = stmt.limit(limit).offset(offset)
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def count_history_by_boat(
        self,
        boat_id: str,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> int:
        """Retorna a contagem total de pacotes de uma embarcação dentro do intervalo temporal."""
        stmt = (
            select(func.count())
            .select_from(Telemetry)
            .where(Telemetry.boat_id == boat_id)
        )
        if from_time is not None:
            stmt = stmt.where(Telemetry.timestamp >= ensure_utc_datetime(from_time))
        if to_time is not None:
            stmt = stmt.where(Telemetry.timestamp <= ensure_utc_datetime(to_time))
        count = await self._session.scalar(stmt)
        return int(count or 0)

    async def list_distinct_boats(self) -> list[str]:
        """Lista os identificadores únicos de embarcações presentes na base."""
        stmt = select(Telemetry.boat_id).distinct().order_by(Telemetry.boat_id)
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def get_boat_stats(
        self,
        boat_id: str,
        since: datetime | None = None,
    ) -> dict[str, Any]:
        """Retorna métricas agregadas da embarcação (média de velocidade e total de pacotes)."""
        stmt = select(
            func.avg(Telemetry.speed_knots).label("avg_speed"),
            func.count(Telemetry.packet_id).label("total_packets"),
        ).where(Telemetry.boat_id == boat_id)
        if since is not None:
            stmt = stmt.where(Telemetry.timestamp >= ensure_utc_datetime(since))

        row = (await self._session.execute(stmt)).one()
        return {
            "avg_speed": float(row.avg_speed) if row.avg_speed is not None else None,
            "total_packets": int(row.total_packets or 0),
        }

    async def get_fleet_avg_speed(self, since: datetime | None = None) -> float | None:
        """Calcula a velocidade média geral de toda a frota."""
        stmt = select(func.avg(Telemetry.speed_knots)).select_from(Telemetry)
        if since is not None:
            stmt = stmt.where(Telemetry.timestamp >= ensure_utc_datetime(since))
        val = await self._session.scalar(stmt)
        return float(val) if val is not None else None

    async def get_latest_global(self) -> Telemetry | None:
        """Retorna o registro de telemetria mais recente de qualquer embarcação."""
        stmt = select(Telemetry).order_by(Telemetry.timestamp.desc()).limit(1)
        return await self._session.scalar(stmt)

    async def get_history_global(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Telemetry]:
        """Retorna o histórico geral paginado em ordem decrescente."""
        stmt = (
            select(Telemetry)
            .order_by(Telemetry.timestamp.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

