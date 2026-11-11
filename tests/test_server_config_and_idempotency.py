"""Testes unitários de configuração do servidor, idempotência UUIDv4 e validação/mapeamento."""

from __future__ import annotations

import asyncio
from datetime import timezone
from uuid import UUID, uuid1, uuid4, uuid5, NAMESPACE_DNS

import pytest

from src.proto import telemetry_pb2
from src.server.config import (
    DEFAULT_GRPC_PORT,
    DEFAULT_SNS_TOPIC_NAME,
    IngestionMode,
    ServerSettings,
)
from src.server.idempotency import (
    IdempotencyGuard,
    InMemoryIdempotencyCache,
    InvalidPacketIdError,
    validate_packet_uuid,
)
from src.server.mapper import TelemetryValidationError, validate_and_map_packet


def _make_proto_packet(
    *,
    message_id: str | None = None,
    boat_id: str = "ferry-ivete-sangalo",
    timestamp_coleta: int = 1762800000000,
    passageiros: int = 320,
    latitude: float = -12.9714,
    longitude: float = -38.5014,
) -> telemetry_pb2.TelemetryPacket:
    return telemetry_pb2.TelemetryPacket(
        message_id=message_id if message_id is not None else str(uuid4()),
        boat_id=boat_id,
        timestamp_coleta=timestamp_coleta,
        passageiros=passageiros,
        navegacao=telemetry_pb2.NavigationData(
            latitude=latitude,
            longitude=longitude,
            velocidade_nos=13.5,
            rumo_graus=245.0,
            status_navegacao=telemetry_pb2.NAVIGATION_STATUS_EM_TRAVESSIA,
        ),
        propulsao=telemetry_pb2.PropulsionData(
            rpm_motor=1420.0,
            temperatura_motor_celsius=81.5,
            pressao_oleo_bar=4.2,
            nivel_combustivel_percentual=78.0,
            consumo_instantaneo_lph=115.0,
        ),
        rede=telemetry_pb2.NetworkDiagnostics(
            rssi_dbm=-74,
            latencia_rtt_ms=32.4,
            perda_pacotes_percentual=0.5,
            tamanho_buffer_local=0,
            tentativa_envio=1,
            tipo_enlace=telemetry_pb2.LINK_TYPE_4G_5G_COSTEIRO,
        ),
    )


def test_server_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "GRPC_HOST",
        "GRPC_PORT",
        "INGESTION_MODE",
        "DIRECT_PATH_ENABLED",
        "SNS_ENABLED",
        "SNS_TOPIC_ARN",
        "SNS_TOPIC_NAME",
        "AWS_ENDPOINT_URL",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = ServerSettings.from_env()
    assert settings.grpc_port == DEFAULT_GRPC_PORT == 50051
    assert settings.ingestion_mode is IngestionMode.AUTO
    assert settings.direct_path_enabled is True
    assert settings.decoupled_path_enabled is False
    assert settings.sns_topic_name == DEFAULT_SNS_TOPIC_NAME == "ferry-telemetry-topic"


def test_server_settings_auto_enables_both_when_sns_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INGESTION_MODE", "auto")
    monkeypatch.setenv(
        "SNS_TOPIC_ARN",
        "arn:aws:sns:us-east-1:000000000000:ferry-telemetry-topic",
    )

    settings = ServerSettings.from_env()
    assert settings.direct_path_enabled is True
    assert settings.decoupled_path_enabled is True


@pytest.mark.parametrize(
    ("mode", "expected_direct", "expected_decoupled"),
    [
        ("direct", True, False),
        ("decoupled", False, True),
        ("both", True, True),
    ],
)
def test_server_settings_explicit_modes(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_direct: bool,
    expected_decoupled: bool,
) -> None:
    monkeypatch.setenv("INGESTION_MODE", mode)
    settings = ServerSettings.from_env()
    assert settings.direct_path_enabled is expected_direct
    assert settings.decoupled_path_enabled is expected_decoupled


def test_server_settings_rejects_invalid_mode_and_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INGESTION_MODE", "invalido")
    with pytest.raises(ValueError, match="INGESTION_MODE"):
        ServerSettings.from_env()

    monkeypatch.setenv("INGESTION_MODE", "direct")
    monkeypatch.setenv("GRPC_PORT", "70000")
    with pytest.raises(ValueError, match="GRPC_PORT"):
        ServerSettings.from_env()


def test_validate_packet_uuid_enforces_uuid_v4() -> None:
    uid = uuid4()
    assert validate_packet_uuid(f"  {uid}  ") == uid

    with pytest.raises(InvalidPacketIdError):
        validate_packet_uuid("")
    with pytest.raises(InvalidPacketIdError):
        validate_packet_uuid("nao-e-uuid")
    with pytest.raises(InvalidPacketIdError, match="versão 4"):
        validate_packet_uuid(str(uuid1()))
    with pytest.raises(InvalidPacketIdError, match="versão 4"):
        validate_packet_uuid(str(uuid5(NAMESPACE_DNS, "ferry")))


def test_in_memory_cache_lru_and_ttl() -> None:
    now = 100.0
    cache = InMemoryIdempotencyCache(max_size=2, ttl_seconds=10.0, clock=lambda: now)
    p1, p2, p3 = uuid4(), uuid4(), uuid4()

    cache.mark_processed(p1)
    cache.mark_processed(p2)
    assert cache.contains(p1) is True  # Atualiza LRU: p2 passa a ser o mais antigo
    cache.mark_processed(p3)
    assert cache.contains(p2) is False
    assert cache.contains(p1) is True
    assert cache.contains(p3) is True

    now += 11.0
    assert cache.contains(p1) is False
    assert cache.contains(p3) is False


async def test_idempotency_guard_checks_cache_before_db_and_serializes_locks() -> None:
    guard = IdempotencyGuard(cache=InMemoryIdempotencyCache(max_size=100, ttl_seconds=60.0))
    packet_id = uuid4()
    db_calls = 0

    async def fake_db_exists(pid: UUID) -> bool:
        nonlocal db_calls
        db_calls += 1
        return pid == packet_id

    assert await guard.is_duplicate(packet_id, fake_db_exists) is True
    assert db_calls == 1

    # Segunda chamada deve bater no cache sem consultar o banco novamente
    assert await guard.is_duplicate(packet_id, fake_db_exists) is True
    assert db_calls == 1

    events: list[str] = []

    async def worker(tag: str) -> None:
        async with guard.lock_packet(packet_id):
            events.append(f"enter-{tag}")
            await asyncio.sleep(0.01)
            events.append(f"exit-{tag}")

    await asyncio.gather(worker("a"), worker("b"))
    assert events in (
        ["enter-a", "exit-a", "enter-b", "exit-b"],
        ["enter-b", "exit-b", "enter-a", "exit-a"],
    )


def test_validate_and_map_packet_maps_record_and_sns_payload() -> None:
    packet = _make_proto_packet()
    mapped = validate_and_map_packet(packet, metadata=[("x-sequence-number", "42")])

    assert mapped.packet_id == UUID(packet.message_id)
    assert mapped.boat_id == "ferry-ivete-sangalo"
    assert mapped.sequence_number == 42
    assert mapped.timestamp.tzinfo == timezone.utc

    assert mapped.record.packet_id == mapped.packet_id
    assert mapped.record.sequence_number == 42
    assert mapped.record.latitude == pytest.approx(-12.9714)
    assert mapped.record.longitude == pytest.approx(-38.5014)
    assert mapped.record.speed_knots == pytest.approx(13.5)
    assert mapped.record.engine_rpm == pytest.approx(1420.0)
    assert mapped.record.network_rssi_dbm == -74

    assert mapped.sns_payload["packet_id"] == packet.message_id
    assert mapped.sns_payload["passageiros"] == 320
    assert mapped.sns_payload["navegacao"]["status_navegacao"] == "NAVIGATION_STATUS_EM_TRAVESSIA"
    assert mapped.sns_attributes["boat_id"] == "ferry-ivete-sangalo"


def test_validate_and_map_packet_rejects_invalid_fields() -> None:
    missing_nav = telemetry_pb2.TelemetryPacket(
        message_id=str(uuid4()),
        boat_id="ferry-1",
        timestamp_coleta=1762800000000,
    )
    with pytest.raises(TelemetryValidationError, match="navegacao"):
        validate_and_map_packet(missing_nav)

    bad_lat = _make_proto_packet(latitude=-95.0)
    with pytest.raises(TelemetryValidationError, match="latitude"):
        validate_and_map_packet(bad_lat)

    bad_nan = _make_proto_packet(longitude=float("nan"))
    with pytest.raises(TelemetryValidationError, match="finito"):
        validate_and_map_packet(bad_nan)

    empty_boat = _make_proto_packet(boat_id="   ")
    with pytest.raises(TelemetryValidationError, match="boat_id"):
        validate_and_map_packet(empty_boat)

