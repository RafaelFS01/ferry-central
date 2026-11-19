"""Testes de integração do TelemetryRepository e camada database com SQLite assíncrono (SCRUM-25)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.database import (
    DatabaseSettings,
    Telemetry,
    TelemetryRecordInput,
    TelemetryRepository,
    normalize_async_database_url,
)
from src.database import session as db_session_module
from src.database.repository import ensure_utc_datetime


def _record(
    *,
    boat_id: str = "ferry-ivete-sangalo",
    sequence_number: int = 1,
    ts: datetime | None = None,
    speed_knots: float | None = 14.0,
) -> TelemetryRecordInput:
    return TelemetryRecordInput(
        packet_id=uuid4(),
        boat_id=boat_id,
        sequence_number=sequence_number,
        timestamp=ts or datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc),
        latitude=-12.9714,
        longitude=-38.5014,
        speed_knots=speed_knots,
        course_heading=240.0,
        hdop=0.9,
        satellites_tracked=12,
        engine_rpm=1500.0,
        engine_temp_celsius=81.0,
        fuel_level_percent=75.0,
        battery_voltage=24.4,
        network_latency_ms=30.0,
        network_rssi_dbm=-70,
    )


def test_database_helpers_repr_and_psycopg2_normalization() -> None:
    assert (
        normalize_async_database_url("postgresql+psycopg2://u:p@host:5432/db")
        == "postgresql+asyncpg://u:p@host:5432/db"
    )

    naive = datetime(2026, 11, 18, 10, 0, 0)
    aware = ensure_utc_datetime(naive)
    assert aware.tzinfo == timezone.utc

    brt = datetime(2026, 11, 18, 7, 0, 0, tzinfo=timezone(timedelta(hours=-3)))
    assert ensure_utc_datetime(brt) == aware

    pid = uuid4()
    row = Telemetry(
        packet_id=pid,
        boat_id="ferry-test",
        sequence_number=9,
        timestamp=aware,
        latitude=-12.9,
        longitude=-38.5,
    )
    rendered = repr(row)
    assert "Telemetry(" in rendered
    assert "ferry-test" in rendered
    assert str(pid) in rendered


async def test_repository_insert_packet_idempotency_and_mapping_input(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    rec = _record(sequence_number=1)
    dict_packet_id = uuid4()
    raw_mapping = {
        "packet_id": dict_packet_id,
        "boat_id": "ferry-dict",
        "sequence_number": 2,
        "timestamp": datetime(2026, 11, 18, 12, 5, 0),  # naive datetime normalizado para UTC
        "latitude": -12.96,
        "longitude": -38.51,
        "speed_knots": 11.5,
    }

    async with sqlite_session_factory() as session:
        repo = TelemetryRepository(session)
        assert await repo.insert_packet(rec) is True
        assert await repo.insert_packet(rec) is False
        assert await repo.insert_packet(raw_mapping) is True
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = TelemetryRepository(session)
        assert await repo.exists_packet(rec.packet_id) is True
        assert await repo.exists_packet(uuid4()) is False

        found = await repo.get_by_packet_id(dict_packet_id)
        assert found is not None
        assert found.boat_id == "ferry-dict"
        assert await repo.get_by_packet_id(uuid4()) is None


async def test_repository_insert_batch_chunking_duplicates_and_validation(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    base_ts = datetime(2026, 11, 18, 13, 0, 0, tzinfo=timezone.utc)
    records = [
        _record(boat_id="ferry-batch", sequence_number=i, ts=base_ts + timedelta(seconds=i * 5))
        for i in range(1, 13)
    ]

    async with sqlite_session_factory() as session:
        repo = TelemetryRepository(session)
        assert await repo.insert_batch([]) == 0
        with pytest.raises(ValueError, match="chunk_size"):
            await repo.insert_batch(records, chunk_size=0)

        inserted_first = await repo.insert_batch(records[:5], chunk_size=3)
        assert inserted_first == 5
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = TelemetryRepository(session)
        inserted_second = await repo.insert_batch(records, chunk_size=4)
        assert inserted_second == 7
        await session.commit()


async def test_repository_queries_history_stats_and_global_views(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    t0 = datetime(2026, 11, 18, 14, 0, 0, tzinfo=timezone.utc)
    boat_a = "ferry-alpha"
    boat_b = "ferry-beta"

    records = [
        _record(boat_id=boat_a, sequence_number=1, ts=t0, speed_knots=10.0),
        _record(boat_id=boat_a, sequence_number=2, ts=t0 + timedelta(minutes=5), speed_knots=14.0),
        _record(boat_id=boat_a, sequence_number=3, ts=t0 + timedelta(minutes=10), speed_knots=18.0),
        _record(boat_id=boat_b, sequence_number=1, ts=t0 + timedelta(minutes=12), speed_knots=20.0),
    ]

    async with sqlite_session_factory() as session:
        repo = TelemetryRepository(session)
        # Base vazia
        assert await repo.get_fleet_avg_speed() is None
        assert await repo.get_latest_global() is None

        await repo.insert_batch(records)
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = TelemetryRepository(session)

        assert await repo.list_distinct_boats() == [boat_a, boat_b]

        latest_a = await repo.get_latest_by_boat(boat_a)
        assert latest_a is not None and latest_a.sequence_number == 3
        assert await repo.get_latest_by_boat("ferry-inexistente") is None

        hist_desc = await repo.get_history_by_boat(boat_a, limit=2, offset=0, order_asc=False)
        assert [r.sequence_number for r in hist_desc] == [3, 2]

        hist_filtered = await repo.get_history_by_boat(
            boat_a,
            from_time=t0 + timedelta(minutes=1),
            to_time=t0 + timedelta(minutes=10),
            order_asc=True,
        )
        assert [r.sequence_number for r in hist_filtered] == [2, 3]

        total_filtered = await repo.count_history_by_boat(
            boat_a,
            from_time=t0 + timedelta(minutes=1),
            to_time=t0 + timedelta(minutes=10),
        )
        assert total_filtered == 2

        stats_a = await repo.get_boat_stats(boat_a)
        assert stats_a["total_packets"] == 3
        assert stats_a["avg_speed"] == pytest.approx(14.0)

        stats_a_recent = await repo.get_boat_stats(boat_a, since=t0 + timedelta(minutes=5))
        assert stats_a_recent["total_packets"] == 2
        assert stats_a_recent["avg_speed"] == pytest.approx(16.0)

        stats_empty = await repo.get_boat_stats("ferry-inexistente")
        assert stats_empty == {"avg_speed": None, "total_packets": 0}

        assert await repo.get_fleet_avg_speed() == pytest.approx(15.5)
        assert await repo.get_fleet_avg_speed(since=t0 + timedelta(minutes=10)) == pytest.approx(19.0)

        latest_global = await repo.get_latest_global()
        assert latest_global is not None and latest_global.boat_id == boat_b

        history_global = await repo.get_history_global(limit=3, offset=1)
        assert len(history_global) == 3
        assert history_global[0].boat_id == boat_a


async def test_session_lifecycle_helpers_singleton_commit_rollback_and_dispose(
    monkeypatch: pytest.MonkeyPatch,
    sqlite_engine: AsyncEngine,
) -> None:
    """Testa get_engine, get_session_factory, get_async_session (commit/rollback) e dispose_engine."""
    await db_session_module.dispose_engine()

    # Verifica montagem dos parâmetros do create_async_db_engine sem abrir conexão real ao Postgres
    captured: dict = {}

    def _fake_create_async_engine(url: str, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return sqlite_engine

    monkeypatch.setattr(db_session_module, "create_async_engine", _fake_create_async_engine)
    cfg = DatabaseSettings(database_url="postgresql+asyncpg://u:p@localhost:5432/ferry")
    engine = db_session_module.create_async_db_engine(cfg)
    assert engine is sqlite_engine
    assert captured["url"] == cfg.database_url
    assert captured["kwargs"]["connect_args"]["server_settings"]["timezone"] == "UTC"

    # Singleton get_engine / get_session_factory
    monkeypatch.setattr(db_session_module, "create_async_db_engine", lambda settings=None: sqlite_engine)
    assert db_session_module.get_engine() is sqlite_engine
    factory = db_session_module.get_session_factory()
    assert factory is db_session_module.get_session_factory()

    # get_async_session realiza commit em sucesso
    rec_ok = _record(boat_id="ferry-commit")
    async with db_session_module.get_async_session() as session:
        assert await TelemetryRepository(session).insert_packet(rec_ok) is True

    async with factory() as session:
        assert await TelemetryRepository(session).exists_packet(rec_ok.packet_id) is True

    # get_async_session realiza rollback em exceção
    rec_fail = _record(boat_id="ferry-rollback")
    with pytest.raises(RuntimeError, match="erro simulado"):
        async with db_session_module.get_async_session() as session:
            await TelemetryRepository(session).insert_packet(rec_fail)
            raise RuntimeError("erro simulado")

    async with factory() as session:
        assert await TelemetryRepository(session).exists_packet(rec_fail.packet_id) is False

    # dispose_engine limpa os singletons globais
    await db_session_module.dispose_engine()
    assert db_session_module._engine is None
    assert db_session_module._session_factory is None
