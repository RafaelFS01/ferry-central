"""Testes de unidade e integração da API REST interna da Central (FastAPI / Pydantic v2)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.config import ApiSettings
from src.api.dependencies import get_api_settings, get_db_session
from src.api.main import create_app
from src.database import (
    TelemetryRecordInput,
    TelemetryRepository,
)
from src.database.models import Telemetry


def _create_record(
    boat_id: str,
    seq: int,
    ts: datetime,
    lat: float = -12.9714,
    lon: float = -38.5014,
    speed: float | None = 15.0,
    heading: float | None = 240.0,
    engine_temp: float | None = 82.0,
    fuel_level: float | None = 80.0,
    battery_v: float | None = 24.5,
) -> TelemetryRecordInput:
    return TelemetryRecordInput(
        packet_id=uuid4(),
        boat_id=boat_id,
        sequence_number=seq,
        timestamp=ts,
        latitude=lat,
        longitude=lon,
        speed_knots=speed,
        course_heading=heading,
        hdop=0.8,
        satellites_tracked=12,
        engine_rpm=1500.0,
        engine_temp_celsius=engine_temp,
        fuel_level_percent=fuel_level,
        battery_voltage=battery_v,
        network_latency_ms=25.0,
        network_rssi_dbm=-68,
    )


@pytest.fixture
async def api_client(session_factory) -> AsyncIterator[httpx.AsyncClient]:
    """Cria cliente de teste HTTPX com sessão de banco injetada a partir da fixture de integração."""
    app = create_app()

    async def _override_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = _override_db_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_endpoint(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_get_boat_latest_not_found(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/api/v1/boats/barco-fantasma/latest")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "barco-fantasma" in data["detail"]


@pytest.mark.asyncio
async def test_get_boat_latest_success(
    api_client: httpx.AsyncClient, session_factory
) -> None:
    boat_id = "ferry-maria-bethania"
    now = datetime.now(timezone.utc)

    rec1 = _create_record(boat_id, 1, now - timedelta(minutes=5), speed=10.0)
    rec2 = _create_record(boat_id, 2, now - timedelta(minutes=1), speed=18.5)

    async with session_factory() as session:
        repo = TelemetryRepository(session)
        await repo.insert_packet(rec1)
        await repo.insert_packet(rec2)
        await session.commit()

    response = await api_client.get(f"/api/v1/boats/{boat_id}/latest")
    assert response.status_code == 200
    data = response.json()
    assert data["boat_id"] == boat_id
    assert data["sequence_number"] == 2
    assert data["speed_knots"] == 18.5
    assert data["packet_id"] == str(rec2.packet_id)


@pytest.mark.asyncio
async def test_get_boat_history_pagination_and_time_filters(
    api_client: httpx.AsyncClient, session_factory
) -> None:
    boat_id = f"ferry-gal-costa-{uuid4().hex[:8]}"
    base_time = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)

    records = [
        _create_record(boat_id, i, base_time + timedelta(minutes=i * 5))
        for i in range(1, 11)  # 10 registros
    ]

    async with session_factory() as session:
        repo = TelemetryRepository(session)
        await repo.insert_batch(records)
        await session.commit()

    # 1. Consulta com paginação (limit=4, offset=2)
    resp = await api_client.get(f"/api/v1/boats/{boat_id}/history?limit=4&offset=2&order=asc")
    assert resp.status_code == 200
    data = resp.json()
    assert data["boat_id"] == boat_id
    assert data["total"] == 10
    assert data["limit"] == 4
    assert data["offset"] == 2
    assert len(data["items"]) == 4
    assert data["items"][0]["sequence_number"] == 3
    assert data["items"][3]["sequence_number"] == 6

    # 2. Filtro temporal com 'from' e 'to'
    from_iso = (base_time + timedelta(minutes=15)).isoformat()
    to_iso = (base_time + timedelta(minutes=35)).isoformat()
    resp_filtered = await api_client.get(
        f"/api/v1/boats/{boat_id}/history?from={from_iso}&to={to_iso}&order=asc"
    )
    assert resp_filtered.status_code == 200
    filtered_data = resp_filtered.json()
    # Minutos 15, 20, 25, 30, 35 -> registros 3, 4, 5, 6, 7 (5 pacotes)
    assert filtered_data["total"] == 5
    assert len(filtered_data["items"]) == 5
    assert filtered_data["items"][0]["sequence_number"] == 3
    assert filtered_data["items"][-1]["sequence_number"] == 7

    # 3. Validação de erro quando from > to
    invalid_resp = await api_client.get(
        f"/api/v1/boats/{boat_id}/history?from={to_iso}&to={from_iso}"
    )
    assert invalid_resp.status_code == 400


@pytest.mark.asyncio
async def test_get_fleet_metrics_summary_and_alerts(
    api_client: httpx.AsyncClient, session_factory
) -> None:
    now = datetime.now(timezone.utc)

    # Barco 1: Operando normalmente (recente, temperatura 82°C, bateria 24.5V, combustivel 70%)
    b1_id = "ferry-normal"
    rec_b1 = _create_record(
        b1_id, 1, now - timedelta(seconds=5), engine_temp=82.0, battery_v=24.5, fuel_level=70.0, speed=16.0
    )

    # Barco 2: Alerta crítico de superaquecimento (temperatura 93°C)
    b2_id = "ferry-superaquecido"
    rec_b2 = _create_record(
        b2_id, 1, now - timedelta(seconds=10), engine_temp=93.0, battery_v=24.0, fuel_level=50.0, speed=14.0
    )

    # Barco 3: Alerta warning (temperatura elevada 89°C, combustivel baixo 12%)
    b3_id = "ferry-combustivel-baixo"
    rec_b3 = _create_record(
        b3_id, 1, now - timedelta(seconds=15), engine_temp=89.0, battery_v=24.0, fuel_level=12.0, speed=12.0
    )

    # Barco 4: Alerta silent (sem comunicação há 2 minutos)
    b4_id = "ferry-silencioso"
    rec_b4 = _create_record(
        b4_id, 1, now - timedelta(minutes=2), engine_temp=80.0, battery_v=24.0, fuel_level=90.0, speed=0.0
    )

    async with session_factory() as session:
        repo = TelemetryRepository(session)
        await repo.insert_batch([rec_b1, rec_b2, rec_b3, rec_b4])
        await session.commit()

    resp = await api_client.get("/api/v1/metrics/fleet")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_boats"] >= 4
    # b1, b2, b3 são ativos (dentro de 30s); b4 é silent
    boats_by_id = {b["boat_id"]: b for b in data["boats"]}

    assert boats_by_id[b1_id]["status"] == "operational"
    assert len(boats_by_id[b1_id]["alerts"]) == 0

    assert boats_by_id[b2_id]["status"] == "critical"
    crit_alert_ids = [a["id"] for a in boats_by_id[b2_id]["alerts"]]
    assert "engine-temp" in crit_alert_ids

    assert boats_by_id[b3_id]["status"] == "warning"
    warn_alert_ids = [a["id"] for a in boats_by_id[b3_id]["alerts"]]
    assert "fuel" in warn_alert_ids
    assert "engine-temp" in warn_alert_ids

    assert boats_by_id[b4_id]["status"] == "silent"
    silent_alert_ids = [a["id"] for a in boats_by_id[b4_id]["alerts"]]
    assert "stale" in silent_alert_ids

    # Validação da velocidade média geral da frota
    assert data["fleet_avg_speed_knots"] is not None
    assert data["fleet_avg_speed_knots"] > 0


@pytest.mark.asyncio
async def test_compatibility_endpoints(
    api_client: httpx.AsyncClient, session_factory
) -> None:
    boat_id = f"ferry-compat-{uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    rec1 = _create_record(boat_id, 1, now - timedelta(seconds=20), speed=11.0)
    rec2 = _create_record(boat_id, 2, now - timedelta(seconds=5), speed=13.0)

    async with session_factory() as session:
        repo = TelemetryRepository(session)
        await repo.insert_batch([rec1, rec2])
        await session.commit()

    # GET /api/telemetry/latest
    resp_latest = await api_client.get(f"/api/telemetry/latest?boat_id={boat_id}")
    assert resp_latest.status_code == 200
    assert resp_latest.json()["sequence_number"] == 2

    # GET /api/telemetry/history
    resp_hist = await api_client.get(f"/api/telemetry/history?boat_id={boat_id}&limit=10")
    assert resp_hist.status_code == 200
    items = resp_hist.json()
    assert isinstance(items, list)
    assert len(items) == 2
