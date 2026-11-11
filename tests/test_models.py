"""Testes estruturais do modelo relacional Telemetry e seus índices."""

from __future__ import annotations

from sqlalchemy import BigInteger, DateTime, Double, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from src.database.models import Telemetry


def test_telemetry_table_columns_and_types() -> None:
    table = Telemetry.__table__
    assert table.name == "telemetria"

    expected_columns = {
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
    assert set(table.columns.keys()) == expected_columns

    assert isinstance(table.c.packet_id.type, PG_UUID)
    assert table.c.packet_id.primary_key is True
    assert table.c.packet_id.nullable is False

    assert isinstance(table.c.boat_id.type, String)
    assert table.c.boat_id.type.length == 50
    assert table.c.boat_id.nullable is False

    assert isinstance(table.c.sequence_number.type, BigInteger)
    assert table.c.sequence_number.nullable is False

    assert isinstance(table.c.timestamp.type, DateTime)
    assert table.c.timestamp.type.timezone is True
    assert table.c.timestamp.nullable is False

    for col_name in (
        "latitude",
        "longitude",
        "speed_knots",
        "course_heading",
        "hdop",
        "engine_rpm",
        "engine_temp_celsius",
        "fuel_level_percent",
        "battery_voltage",
        "network_latency_ms",
    ):
        assert isinstance(table.c[col_name].type, Double)

    for col_name in ("satellites_tracked", "network_rssi_dbm"):
        assert isinstance(table.c[col_name].type, Integer)

    assert isinstance(table.c.created_at.type, DateTime)
    assert table.c.created_at.type.timezone is True
    assert table.c.created_at.server_default is not None
    assert table.c.created_at.nullable is False


def test_telemetry_indexes() -> None:
    indexes = {idx.name: idx for idx in Telemetry.__table__.indexes}

    assert "idx_telemetria_boat_timestamp" in indexes
    boat_ts_idx = indexes["idx_telemetria_boat_timestamp"]
    assert boat_ts_idx.unique is False
    assert [expr.element.name if hasattr(expr, "element") else expr.name for expr in boat_ts_idx.expressions] == [
        "boat_id",
        "timestamp",
    ]

    assert "idx_telemetria_packet_id" in indexes
    pkt_idx = indexes["idx_telemetria_packet_id"]
    assert pkt_idx.unique is True
    assert [col.name for col in pkt_idx.columns] == ["packet_id"]

