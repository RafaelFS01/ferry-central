"""Testes unitários de schemas Protobuf, serialização binária e parsers de ingestão (SCRUM-25)."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from src.proto import telemetry_pb2
from src.server.idempotency import InvalidPacketIdError
from src.server.mapper import (
    MAX_BOAT_ID_LENGTH,
    SEQUENCE_METADATA_KEY,
    TelemetryValidationError,
    validate_and_map_packet,
)
from src.worker.parser import CorruptedMessageError, parse_sqs_message


def _build_valid_packet(
    *,
    message_id: str | None = None,
    boat_id: str = "ferry-ivete-sangalo",
    timestamp_coleta: int = 1762800000000,
    passageiros: int = 240,
    include_propulsao: bool = True,
    include_rede: bool = True,
) -> telemetry_pb2.TelemetryPacket:
    kwargs: dict = {
        "message_id": message_id if message_id is not None else str(uuid4()),
        "boat_id": boat_id,
        "timestamp_coleta": timestamp_coleta,
        "passageiros": passageiros,
        "navegacao": telemetry_pb2.NavigationData(
            latitude=-12.9714,
            longitude=-38.5014,
            velocidade_nos=13.8,
            rumo_graus=242.5,
            status_navegacao=telemetry_pb2.NAVIGATION_STATUS_EM_TRAVESSIA,
        ),
    }
    if include_propulsao:
        kwargs["propulsao"] = telemetry_pb2.PropulsionData(
            rpm_motor=1550.0,
            temperatura_motor_celsius=81.2,
            pressao_oleo_bar=4.3,
            nivel_combustivel_percentual=74.5,
            consumo_instantaneo_lph=118.4,
        )
    if include_rede:
        kwargs["rede"] = telemetry_pb2.NetworkDiagnostics(
            rssi_dbm=-73,
            latencia_rtt_ms=29.5,
            perda_pacotes_percentual=0.4,
            tamanho_buffer_local=2,
            tentativa_envio=1,
            tipo_enlace=telemetry_pb2.LINK_TYPE_4G_5G_COSTEIRO,
        )
    return telemetry_pb2.TelemetryPacket(**kwargs)


# ---------------------------------------------------------------------------
# 1. Validação do Contrato e Serialização Binária Protobuf
# ---------------------------------------------------------------------------


def test_protobuf_descriptor_contract_package_service_and_enums() -> None:
    descriptor = telemetry_pb2.DESCRIPTOR
    assert descriptor.package == "ferry.telemetry.v1"

    service = descriptor.services_by_name["TelemetryService"]
    assert service.full_name == "ferry.telemetry.v1.TelemetryService"
    rpc = service.methods_by_name["EnviarTelemetria"]
    assert rpc.input_type.name == "TelemetryPacket"
    assert rpc.output_type.name == "TelemetryAck"
    assert rpc.client_streaming is False
    assert rpc.server_streaming is False

    assert telemetry_pb2.AckStatus.Name(telemetry_pb2.ACK_STATUS_ACEITO) == "ACK_STATUS_ACEITO"
    assert (
        telemetry_pb2.AckStatus.Name(telemetry_pb2.ACK_STATUS_DUPLICADO_IGNORADO)
        == "ACK_STATUS_DUPLICADO_IGNORADO"
    )
    assert (
        telemetry_pb2.AckStatus.Name(telemetry_pb2.ACK_STATUS_REJEITADO)
        == "ACK_STATUS_REJEITADO"
    )


@pytest.mark.parametrize(
    "nav_status",
    [
        telemetry_pb2.NAVIGATION_STATUS_UNSPECIFIED,
        telemetry_pb2.NAVIGATION_STATUS_ATRACADO,
        telemetry_pb2.NAVIGATION_STATUS_EM_TRAVESSIA,
        telemetry_pb2.NAVIGATION_STATUS_MANOBRA,
        telemetry_pb2.NAVIGATION_STATUS_EMERGENCIA,
    ],
)
@pytest.mark.parametrize(
    "link_type",
    [
        telemetry_pb2.LINK_TYPE_UNSPECIFIED,
        telemetry_pb2.LINK_TYPE_RADIO_VHF_MARITIMO,
        telemetry_pb2.LINK_TYPE_4G_5G_COSTEIRO,
        telemetry_pb2.LINK_TYPE_SATELITAL,
        telemetry_pb2.LINK_TYPE_WIFI_TERMINAL,
    ],
)
def test_protobuf_telemetry_packet_wire_roundtrip(
    nav_status: telemetry_pb2.NavigationStatus,
    link_type: telemetry_pb2.LinkType,
) -> None:
    original = _build_valid_packet()
    original.navegacao.status_navegacao = nav_status
    original.rede.tipo_enlace = link_type

    wire_bytes = original.SerializeToString()
    assert len(wire_bytes) > 0

    decoded = telemetry_pb2.TelemetryPacket()
    decoded.ParseFromString(wire_bytes)

    assert decoded.message_id == original.message_id
    assert decoded.boat_id == original.boat_id
    assert decoded.timestamp_coleta == original.timestamp_coleta
    assert decoded.passageiros == original.passageiros
    assert decoded.navegacao.latitude == pytest.approx(original.navegacao.latitude)
    assert decoded.navegacao.longitude == pytest.approx(original.navegacao.longitude)
    assert decoded.navegacao.status_navegacao == nav_status
    assert decoded.propulsao.rpm_motor == pytest.approx(original.propulsao.rpm_motor)
    assert decoded.rede.tipo_enlace == link_type


def test_protobuf_telemetry_ack_wire_roundtrip() -> None:
    packet_id = str(uuid4())
    ack = telemetry_pb2.TelemetryAck(
        message_id=packet_id,
        sucesso=True,
        duplicado=True,
        processado_em=1762800001234,
        mensagem="Pacote duplicado ignorado (idempotência).",
        status=telemetry_pb2.ACK_STATUS_DUPLICADO_IGNORADO,
    )
    decoded = telemetry_pb2.TelemetryAck()
    decoded.ParseFromString(ack.SerializeToString())

    assert decoded.message_id == packet_id
    assert decoded.sucesso is True
    assert decoded.duplicado is True
    assert decoded.processado_em == 1762800001234
    assert decoded.status == telemetry_pb2.ACK_STATUS_DUPLICADO_IGNORADO


# ---------------------------------------------------------------------------
# 2. Parser / Mapper Protobuf -> TelemetryRecordInput & SNS Payload
# ---------------------------------------------------------------------------


def test_validate_and_map_packet_without_optional_submessages() -> None:
    packet = _build_valid_packet(include_propulsao=False, include_rede=False)
    mapped = validate_and_map_packet(packet)

    assert mapped.packet_id == UUID(packet.message_id)
    assert mapped.sequence_number == packet.timestamp_coleta
    assert mapped.record.engine_rpm is None
    assert mapped.record.engine_temp_celsius is None
    assert mapped.record.fuel_level_percent is None
    assert mapped.record.network_latency_ms is None
    assert mapped.record.network_rssi_dbm is None
    assert mapped.sns_payload["propulsao"] is None
    assert mapped.sns_payload["rede"] is None


def test_validate_and_map_packet_sequence_number_metadata_variants() -> None:
    packet = _build_valid_packet()

    # Header case-insensitive e valor em bytes
    mapped_bytes = validate_and_map_packet(
        packet,
        metadata=[("other-header", "ignored"), ("X-Sequence-Number", b"  108 ")],
    )
    assert mapped_bytes.sequence_number == 108
    assert mapped_bytes.record.sequence_number == 108

    # Header em branco cai para fallback timestamp_coleta
    mapped_blank = validate_and_map_packet(
        packet,
        metadata=[(SEQUENCE_METADATA_KEY, "   ")],
    )
    assert mapped_blank.sequence_number == packet.timestamp_coleta

    # Valor não numérico rejeitado
    with pytest.raises(TelemetryValidationError, match=SEQUENCE_METADATA_KEY):
        validate_and_map_packet(packet, metadata=[(SEQUENCE_METADATA_KEY, "abc")])

    # Valor negativo rejeitado
    with pytest.raises(TelemetryValidationError, match="negativo"):
        validate_and_map_packet(packet, metadata=[(SEQUENCE_METADATA_KEY, "-1")])


def test_validate_and_map_packet_boundary_values_accepted() -> None:
    packet = _build_valid_packet(boat_id="a" * MAX_BOAT_ID_LENGTH, passageiros=0)
    packet.navegacao.latitude = -90.0
    packet.navegacao.longitude = 180.0
    packet.navegacao.velocidade_nos = 0.0
    packet.navegacao.rumo_graus = 360.0
    packet.propulsao.rpm_motor = 0.0
    packet.propulsao.nivel_combustivel_percentual = 100.0
    packet.rede.latencia_rtt_ms = 0.0
    packet.rede.perda_pacotes_percentual = 100.0

    mapped = validate_and_map_packet(packet)
    assert len(mapped.boat_id) == MAX_BOAT_ID_LENGTH
    assert mapped.record.latitude == -90.0
    assert mapped.record.longitude == 180.0
    assert mapped.record.speed_knots == 0.0
    assert mapped.record.course_heading == 360.0
    assert mapped.record.fuel_level_percent == 100.0
    assert mapped.record.network_latency_ms == 0.0


@pytest.mark.parametrize(
    ("mutator", "expected_error", "match_pattern"),
    [
        (lambda p: setattr(p, "message_id", "not-a-uuid"), InvalidPacketIdError, "UUIDv4"),
        (
            lambda p: setattr(p, "boat_id", "x" * (MAX_BOAT_ID_LENGTH + 1)),
            TelemetryValidationError,
            "limite",
        ),
        (lambda p: setattr(p, "timestamp_coleta", 0), TelemetryValidationError, "positivo"),
        (lambda p: setattr(p, "timestamp_coleta", -100), TelemetryValidationError, "positivo"),
        (
            lambda p: setattr(p, "timestamp_coleta", 10**18),
            TelemetryValidationError,
            "intervalo",
        ),
        (lambda p: setattr(p, "passageiros", -1), TelemetryValidationError, "passageiros"),
        (lambda p: setattr(p.navegacao, "latitude", 90.01), TelemetryValidationError, "latitude"),
        (
            lambda p: setattr(p.navegacao, "longitude", -180.01),
            TelemetryValidationError,
            "longitude",
        ),
        (
            lambda p: setattr(p.navegacao, "longitude", math.inf),
            TelemetryValidationError,
            "finito",
        ),
        (
            lambda p: setattr(p.navegacao, "velocidade_nos", -0.5),
            TelemetryValidationError,
            "velocidade_nos",
        ),
        (
            lambda p: setattr(p.navegacao, "rumo_graus", -1.0),
            TelemetryValidationError,
            "rumo_graus",
        ),
        (
            lambda p: setattr(p.navegacao, "rumo_graus", 360.1),
            TelemetryValidationError,
            "rumo_graus",
        ),
        (
            lambda p: setattr(p.propulsao, "rpm_motor", -10.0),
            TelemetryValidationError,
            "rpm_motor",
        ),
        (
            lambda p: setattr(p.propulsao, "temperatura_motor_celsius", math.nan),
            TelemetryValidationError,
            "finito",
        ),
        (
            lambda p: setattr(p.propulsao, "nivel_combustivel_percentual", -0.1),
            TelemetryValidationError,
            "nivel_combustivel_percentual",
        ),
        (
            lambda p: setattr(p.propulsao, "nivel_combustivel_percentual", 100.1),
            TelemetryValidationError,
            "nivel_combustivel_percentual",
        ),
        (
            lambda p: setattr(p.rede, "latencia_rtt_ms", -5.0),
            TelemetryValidationError,
            "latencia_rtt_ms",
        ),
        (
            lambda p: setattr(p.rede, "perda_pacotes_percentual", -1.0),
            TelemetryValidationError,
            "perda_pacotes_percentual",
        ),
        (
            lambda p: setattr(p.rede, "perda_pacotes_percentual", 101.0),
            TelemetryValidationError,
            "perda_pacotes_percentual",
        ),
    ],
)
def test_validate_and_map_packet_rejects_domain_violations(
    mutator,
    expected_error: type[Exception],
    match_pattern: str,
) -> None:
    packet = _build_valid_packet()
    mutator(packet)
    with pytest.raises(expected_error, match=match_pattern):
        validate_and_map_packet(packet)


def test_protobuf_sns_payload_roundtrip_compatibility_with_worker_parser() -> None:
    """Garante compatibilidade canônica entre mapper gRPC -> SNS -> parser SQS do worker."""
    packet = _build_valid_packet()
    mapped = validate_and_map_packet(packet, metadata=[(SEQUENCE_METADATA_KEY, "77")])

    sns_envelope = {
        "Type": "Notification",
        "MessageId": "sns-test-001",
        "TopicArn": "arn:aws:sns:us-east-1:000000000000:ferry-telemetria-topic",
        "Message": json.dumps(mapped.sns_payload),
    }

    parsed_by_worker = parse_sqs_message(json.dumps(sns_envelope))
    assert parsed_by_worker.packet_id == mapped.record.packet_id
    assert parsed_by_worker.boat_id == mapped.record.boat_id
    assert parsed_by_worker.sequence_number == mapped.record.sequence_number == 77
    assert parsed_by_worker.timestamp == mapped.record.timestamp
    assert parsed_by_worker.latitude == pytest.approx(mapped.record.latitude)
    assert parsed_by_worker.longitude == pytest.approx(mapped.record.longitude)
    assert parsed_by_worker.speed_knots == pytest.approx(mapped.record.speed_knots)
    assert parsed_by_worker.passengers == mapped.record.passengers == 240
    assert parsed_by_worker.course_heading == pytest.approx(mapped.record.course_heading)
    assert parsed_by_worker.engine_rpm == pytest.approx(mapped.record.engine_rpm)
    assert parsed_by_worker.engine_temp_celsius == pytest.approx(mapped.record.engine_temp_celsius)
    assert parsed_by_worker.fuel_level_percent == pytest.approx(mapped.record.fuel_level_percent)
    assert parsed_by_worker.network_latency_ms == pytest.approx(mapped.record.network_latency_ms)
    assert parsed_by_worker.network_rssi_dbm == mapped.record.network_rssi_dbm


# ---------------------------------------------------------------------------
# 3. Casos de borda do parser SQS/SNS (src/worker/parser.py)
# ---------------------------------------------------------------------------


def test_worker_parser_handles_datetime_variants_and_optional_telemetry_fields() -> None:
    packet_id = str(uuid4())
    naive_dt = datetime(2026, 11, 18, 15, 30, 0)
    record = parse_sqs_message(
        {
            "Type": "Notification",
            "Message": {
                "packet_id": packet_id,
                "boat_id": "ferry-zumbi",
                "timestamp": naive_dt,
                "navegacao": {
                    "latitude": -12.95,
                    "longitude": -38.51,
                    "hdop": 0.9,
                    "satellites_tracked": 11,
                },
            },
        }
    )
    assert record.packet_id == UUID(packet_id)
    assert record.timestamp.tzinfo == timezone.utc
    assert record.sequence_number == 0
    assert record.hdop == pytest.approx(0.9)
    assert record.satellites_tracked == 11

    aware_dt = datetime(2026, 11, 18, 15, 30, 0, tzinfo=timezone.utc)
    record_aware = parse_sqs_message(
        {
            "packet_id": str(uuid4()),
            "boat_id": "ferry-zumbi",
            "timestamp": aware_dt,
            "latitude": -12.95,
            "longitude": -38.51,
            "hdop": 1.1,
            "satellites_tracked": 9,
            "network_latency_ms": 22.0,
            "network_rssi_dbm": -75,
        }
    )
    assert record_aware.timestamp == aware_dt
    assert record_aware.network_latency_ms == pytest.approx(22.0)
    assert record_aware.network_rssi_dbm == -75

    record_naive_iso = parse_sqs_message(
        {
            "packet_id": str(uuid4()),
            "boat_id": "ferry-zumbi",
            "timestamp": "2026-11-18T15:30:00",
            "latitude": -12.95,
            "longitude": -38.51,
        }
    )
    assert record_naive_iso.timestamp.tzinfo == timezone.utc


@pytest.mark.parametrize(
    ("payload", "match_pattern"),
    [
        (12345, "Tipo de payload não suportado"),
        ({"Type": "Notification", "Message": 12345}, "não é um objeto"),
        ({"Type": "Notification", "Message": "[1, 2, 3]"}, "desempacotada deve ser um objeto"),
        (
            {
                "packet_id": str(uuid4()),
                "boat_id": "ferry-1",
                "sequence_number": "not-int",
                "timestamp": "2026-11-18T10:00:00Z",
                "latitude": -12.9,
                "longitude": -38.5,
            },
            "sequence_number",
        ),
        (
            {
                "packet_id": str(uuid4()),
                "boat_id": "ferry-1",
                "sequence_number": 1,
                "timestamp_coleta": -10,
                "latitude": -12.9,
                "longitude": -38.5,
            },
            "timestamp_coleta",
        ),
        (
            {
                "packet_id": str(uuid4()),
                "boat_id": "ferry-1",
                "latitude": -12.9,
                "longitude": -38.5,
            },
            "ausentes",
        ),
        (
            {
                "packet_id": str(uuid4()),
                "boat_id": "ferry-1",
                "timestamp": "2026-11-18T10:00:00Z",
                "latitude": "abc",
                "longitude": -38.5,
            },
            "numérico",
        ),
        (
            {
                "packet_id": str(uuid4()),
                "boat_id": "ferry-1",
                "timestamp": "2026-11-18T10:00:00Z",
                "latitude": float("nan"),
                "longitude": -38.5,
            },
            "finito",
        ),
        (
            {
                "packet_id": str(uuid4()),
                "boat_id": "ferry-1",
                "timestamp": "2026-11-18T10:00:00Z",
                "latitude": -12.9,
                "longitude": -38.5,
                "satellites_tracked": -2,
            },
            "satellites_tracked",
        ),
        (
            {
                "packet_id": str(uuid4()),
                "boat_id": "ferry-1",
                "timestamp": "2026-11-18T10:00:00Z",
                "latitude": -12.9,
                "longitude": -38.5,
                "network_latency_ms": -5.0,
            },
            "Latência de rede",
        ),
        (
            {
                "packet_id": str(uuid4()),
                "boat_id": "ferry-1",
                "timestamp": "2026-11-18T10:00:00Z",
                "latitude": -12.9,
                "longitude": -38.5,
                "network_rssi_dbm": "bad-rssi",
            },
            "RSSI de rede inválido",
        ),
        (
            {
                "packet_id": str(uuid4()),
                "boat_id": "ferry-1",
                "timestamp": "2026-11-18T10:00:00Z",
                "latitude": -12.9,
                "longitude": -38.5,
                "passageiros": -3,
            },
            "passageiros",
        ),
    ],
)
def test_worker_parser_edge_error_cases(payload, match_pattern: str) -> None:
    with pytest.raises(CorruptedMessageError, match=match_pattern):
        parse_sqs_message(payload)
