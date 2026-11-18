"""Testes unitários para o analisador de mensagens SQS/SNS."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from src.worker.parser import CorruptedMessageError, parse_sqs_message


def _valid_nested_payload() -> dict:
    return {
        "packet_id": str(uuid4()),
        "boat_id": "ferry-ivete-sangalo",
        "sequence_number": 42,
        "timestamp": "2026-11-14T14:30:00+00:00",
        "passageiros": 150,
        "navegacao": {
            "latitude": -12.9714,
            "longitude": -38.5014,
            "velocidade_nos": 14.5,
            "rumo_graus": 240.0,
            "status_navegacao": "EM_TRANSITO",
        },
        "propulsao": {
            "rpm_motor": 1800.0,
            "temperatura_motor_celsius": 82.5,
            "nivel_combustivel_percentual": 75.0,
        },
        "rede": {
            "latencia_rtt_ms": 32.1,
            "rssi_dbm": -68,
        },
    }


def test_parse_valid_nested_json_string() -> None:
    data = _valid_nested_payload()
    record = parse_sqs_message(json.dumps(data))

    assert record.packet_id == UUID(data["packet_id"])
    assert record.boat_id == "ferry-ivete-sangalo"
    assert record.sequence_number == 42
    assert record.latitude == -12.9714
    assert record.longitude == -38.5014
    assert record.speed_knots == 14.5
    assert record.course_heading == 240.0
    assert record.engine_rpm == 1800.0
    assert record.engine_temp_celsius == 82.5
    assert record.fuel_level_percent == 75.0
    assert record.network_latency_ms == 32.1
    assert record.network_rssi_dbm == -68


def test_parse_valid_sns_notification_envelope() -> None:
    inner_data = _valid_nested_payload()
    sns_envelope = {
        "Type": "Notification",
        "MessageId": "sns-12345",
        "TopicArn": "arn:aws:sns:us-east-1:000000000000:ferry-telemetria-topic",
        "Message": json.dumps(inner_data),
        "Timestamp": "2026-11-14T14:30:01.000Z",
    }

    record = parse_sqs_message(json.dumps(sns_envelope))
    assert record.packet_id == UUID(inner_data["packet_id"])
    assert record.boat_id == inner_data["boat_id"]


def test_parse_valid_flat_payload_with_timestamp_coleta_ms() -> None:
    p_id = str(uuid4())
    flat_data = {
        "message_id": p_id,
        "boat_id": "ferry-maria-bethania",
        "sequence_number": 100,
        "timestamp_coleta": 1794667200000,
        "latitude": -12.98,
        "longitude": -38.52,
        "speed_knots": 12.0,
        "course_heading": 180.0,
        "engine_rpm": 1500.0,
        "battery_voltage": 24.5,
    }

    record = parse_sqs_message(flat_data)
    assert record.packet_id == UUID(p_id)
    assert record.boat_id == "ferry-maria-bethania"
    assert record.timestamp == datetime.fromtimestamp(1794667200, tz=timezone.utc)
    assert record.battery_voltage == 24.5


@pytest.mark.parametrize(
    ("corrupted_body", "match_str"),
    [
        ("", "Corpo da mensagem SQS está vazio"),
        ("   ", "Corpo da mensagem SQS está vazio"),
        ("{not valid json", "Payload JSON malformado"),
        ("[1, 2, 3]", "Carga útil JSON deve ser um objeto"),
        ('"string"', "Carga útil JSON deve ser um objeto"),
        (
            json.dumps({"Type": "Notification", "Message": "{malformed inner json"}),
            "Corpo interno 'Message' de notificação SNS malformado",
        ),
        (
            json.dumps({"boat_id": "ferry-1"}),
            "Campo obrigatório 'packet_id'",
        ),
        (
            json.dumps({"packet_id": "not-a-valid-uuid", "boat_id": "ferry-1"}),
            "packet_id inválido como UUID",
        ),
        (
            json.dumps({"packet_id": str(uuid4()), "boat_id": ""}),
            "Campo obrigatório 'boat_id' ausente",
        ),
        (
            json.dumps({"packet_id": str(uuid4()), "boat_id": "a" * 51}),
            "Campo 'boat_id' excede limite",
        ),
        (
            json.dumps(
                {
                    "packet_id": str(uuid4()),
                    "boat_id": "ferry-1",
                    "sequence_number": -1,
                    "timestamp": "2026-11-14T10:00:00Z",
                }
            ),
            "não pode ser negativo",
        ),
        (
            json.dumps(
                {
                    "packet_id": str(uuid4()),
                    "boat_id": "ferry-1",
                    "timestamp": "not-a-date",
                }
            ),
            "Formato de timestamp ISO 8601 inválido",
        ),
        (
            json.dumps(
                {
                    "packet_id": str(uuid4()),
                    "boat_id": "ferry-1",
                    "timestamp": "2026-11-14T10:00:00Z",
                }
            ),
            "Campos de coordenadas GPS",
        ),
        (
            json.dumps(
                {
                    "packet_id": str(uuid4()),
                    "boat_id": "ferry-1",
                    "timestamp": "2026-11-14T10:00:00Z",
                    "latitude": 95.0,  # Fora de [-90, 90]
                    "longitude": -38.5,
                }
            ),
            "fora do intervalo",
        ),
        (
            json.dumps(
                {
                    "packet_id": str(uuid4()),
                    "boat_id": "ferry-1",
                    "timestamp": "2026-11-14T10:00:00Z",
                    "latitude": -12.5,
                    "longitude": -200.0,  # Fora de [-180, 180]
                }
            ),
            "fora do intervalo",
        ),
        (
            json.dumps(
                {
                    "packet_id": str(uuid4()),
                    "boat_id": "ferry-1",
                    "timestamp": "2026-11-14T10:00:00Z",
                    "latitude": -12.5,
                    "longitude": -38.5,
                    "speed_knots": -1.0,
                }
            ),
            "Velocidade náutica não pode ser negativa",
        ),
        (
            json.dumps(
                {
                    "packet_id": str(uuid4()),
                    "boat_id": "ferry-1",
                    "timestamp": "2026-11-14T10:00:00Z",
                    "latitude": -12.5,
                    "longitude": -38.5,
                    "course_heading": 400.0,
                }
            ),
            "Rumo em graus fora do intervalo",
        ),
        (
            json.dumps(
                {
                    "packet_id": str(uuid4()),
                    "boat_id": "ferry-1",
                    "timestamp": "2026-11-14T10:00:00Z",
                    "latitude": -12.5,
                    "longitude": -38.5,
                    "engine_rpm": -100.0,
                }
            ),
            "RPM do motor não pode ser negativo",
        ),
        (
            json.dumps(
                {
                    "packet_id": str(uuid4()),
                    "boat_id": "ferry-1",
                    "timestamp": "2026-11-14T10:00:00Z",
                    "latitude": -12.5,
                    "longitude": -38.5,
                    "fuel_level_percent": 110.0,
                }
            ),
            "Nível de combustível percentual fora de",
        ),
    ],
)
def test_parse_sqs_message_corrupted_payloads(corrupted_body: str, match_str: str) -> None:
    with pytest.raises(CorruptedMessageError, match=match_str):
        parse_sqs_message(corrupted_body)
