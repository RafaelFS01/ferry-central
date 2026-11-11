"""Testes de integração assíncronos contra PostgreSQL 18 (Alembic + SQLAlchemy + asyncpg)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.database import (
    DatabaseSettings,
    TelemetryRecordInput,
    TelemetryRepository,
    create_async_db_engine,
    create_session_factory,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _build_alembic_config() -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return cfg


def _make_packet(
    boat_id: str = "ferry-ivete-sangalo",
    sequence_number: int = 1,
    ts: datetime | None = None,
) -> TelemetryRecordInput:
    return TelemetryRecordInput(
        packet_id=uuid4(),
        boat_id=boat_id,
        sequence_number=sequence_number,
        timestamp=ts or datetime.now(timezone.utc),
        latitude=-12.9714,
        longitude=-38.5014,
        speed_knots=14.2,
        course_heading=245.5,
        hdop=0.9,
        satellites_tracked=12,
        engine_rpm=1450.0,
        engine_temp_celsius=82.4,
        fuel_level_percent=76.5,
        battery_voltage=24.3,
        network_latency_ms=34.8,
        network_rssi_dbm=-72,
    )


@pytest.fixture
async def db_engine() -> AsyncEngine:
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
    return create_session_factory(db_engine)


async def test_alembic_upgrade_downgrade_cycle(db_engine: AsyncEngine) -> None:
    alembic_cfg = _build_alembic_config()

    import asyncio

    await asyncio.to_thread(command.downgrade, alembic_cfg, "base")
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

    async with db_engine.connect() as conn:
        columns_result = await conn.execute(
            text(
                """
                SELECT column_name, data_type, character_maximum_length, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'telemetria'
                ORDER BY ordinal_position
                """
            )
        )
        columns = {row.column_name: row for row in columns_result}

        assert set(columns.keys()) == {
            "packet_id",
            "boat_id",
            "sequence_number",
            "timestamp",
            "latitude",
            "longitude",
            "speed_knots",
            "course_heading",
            "hdop",
            "satellites_tracked",
            "engine_rpm",
            "engine_temp_celsius",
            "fuel_level_percent",
            "battery_voltage",
            "network_latency_ms",
            "network_rssi_dbm",
            "created_at",
        }
        assert columns["packet_id"].data_type == "uuid"
        assert columns["boat_id"].data_type == "character varying"
        assert columns["boat_id"].character_maximum_length == 50
        assert columns["sequence_number"].data_type == "bigint"
        assert columns["timestamp"].data_type == "timestamp with time zone"
        assert columns["created_at"].data_type == "timestamp with time zone"
        assert "now()" in (columns["created_at"].column_default or "")

        indexes_result = await conn.execute(
            text(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = 'telemetria'
                """
            )
        )
        indexes = {row.indexname: row.indexdef for row in indexes_result}

        assert "idx_telemetria_boat_timestamp" in indexes
        assert "boat_id" in indexes["idx_telemetria_boat_timestamp"]
        assert '"timestamp" DESC' in indexes["idx_telemetria_boat_timestamp"] or "timestamp DESC" in indexes["idx_telemetria_boat_timestamp"]

        assert "idx_telemetria_packet_id" in indexes
        assert "CREATE UNIQUE INDEX" in indexes["idx_telemetria_packet_id"]
        assert "(packet_id)" in indexes["idx_telemetria_packet_id"]


async def test_async_engine_uses_asyncpg_and_utc_timezone(
    db_engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert db_engine.dialect.driver == "asyncpg"

    async with session_factory() as session:
        tz = await session.scalar(text("SHOW TIME ZONE"))
        assert tz == "UTC"


async def test_insert_packet_idempotency_and_queries(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    boat_id = f"ferry-test-{uuid4().hex[:8]}"
    t0 = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
    p1 = _make_packet(boat_id=boat_id, sequence_number=1, ts=t0)
    p2 = _make_packet(boat_id=boat_id, sequence_number=2, ts=t0 + timedelta(seconds=5))

    async with session_factory() as session:
        repo = TelemetryRepository(session)
        assert await repo.insert_packet(p1) is True
        # Reenvio com mesmo packet_id deve ser ignorado sem erro
        assert await repo.insert_packet(p1) is False
        assert await repo.insert_packet(p2) is True
        await session.commit()

    async with session_factory() as session:
        repo = TelemetryRepository(session)
        assert await repo.exists_packet(p1.packet_id) is True

        latest = await repo.get_latest_by_boat(boat_id)
        assert latest is not None
        assert latest.packet_id == p2.packet_id
        assert latest.sequence_number == 2
        assert latest.created_at is not None
        assert latest.created_at.tzinfo is not None

        history = await repo.get_history_by_boat(boat_id, limit=10)
        assert [row.packet_id for row in history] == [p2.packet_id, p1.packet_id]


async def test_insert_batch_handles_duplicates_and_high_throughput(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    boat_id = f"ferry-batch-{uuid4().hex[:8]}"
    base_ts = datetime(2026, 11, 10, 14, 0, 0, tzinfo=timezone.utc)

    packets = [
        _make_packet(
            boat_id=boat_id,
            sequence_number=i,
            ts=base_ts + timedelta(seconds=i * 5),
        )
        for i in range(1, 251)
    ]

    # Insere primeiros 100 e depois envia lote de 250 com 100 duplicados
    async with session_factory() as session:
        repo = TelemetryRepository(session)
        first_inserted = await repo.insert_batch(packets[:100])
        assert first_inserted == 100
        await session.commit()

    async with session_factory() as session:
        repo = TelemetryRepository(session)
        second_inserted = await repo.insert_batch(packets, chunk_size=75)
        assert second_inserted == 150
        await session.commit()

    async with session_factory() as session:
        total = await session.scalar(
            text("SELECT count(*) FROM telemetria WHERE boat_id = :boat_id"),
            {"boat_id": boat_id},
        )
        assert total == 250

