"""Validação de payloads Protobuf e mapeamento para PostgreSQL e SNS."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.database.repository import TelemetryRecordInput
from src.proto import telemetry_pb2
from src.server.idempotency import validate_packet_uuid

MAX_BOAT_ID_LENGTH = 50
SEQUENCE_METADATA_KEY = "x-sequence-number"


class TelemetryValidationError(ValueError):
    """Erro de validação semântica/estrutural de um TelemetryPacket."""


@dataclass(frozen=True, slots=True)
class MappedTelemetry:
    """Representação validada e normalizada pronta para Direct e Decoupled paths."""

    packet_id: UUID
    boat_id: str
    sequence_number: int
    timestamp: datetime
    record: TelemetryRecordInput
    sns_payload: dict[str, Any]
    sns_attributes: dict[str, str]


def _require_finite(value: float, field_name: str) -> float:
    if not math.isfinite(value):
        raise TelemetryValidationError(
            f"Campo '{field_name}' deve ser um número finito (recebido {value!r})."
        )
    return float(value)


def _extract_sequence_number(
    packet: telemetry_pb2.TelemetryPacket,
    metadata: Sequence[tuple[str, str | bytes]] | None,
) -> int:
    if metadata:
        for key, raw_value in metadata:
            if key.lower() != SEQUENCE_METADATA_KEY:
                continue
            text_value = (
                raw_value.decode("utf-8", errors="ignore")
                if isinstance(raw_value, bytes)
                else str(raw_value)
            ).strip()
            if not text_value:
                continue
            try:
                parsed = int(text_value)
            except ValueError as exc:
                raise TelemetryValidationError(
                    f"Metadado '{SEQUENCE_METADATA_KEY}' inválido: {text_value!r}."
                ) from exc
            if parsed < 0:
                raise TelemetryValidationError(
                    f"Metadado '{SEQUENCE_METADATA_KEY}' não pode ser negativo."
                )
            return parsed

    return int(packet.timestamp_coleta)


def _timestamp_ms_to_utc(timestamp_ms: int) -> datetime:
    if timestamp_ms <= 0:
        raise TelemetryValidationError(
            "Campo 'timestamp_coleta' deve ser um Epoch em milissegundos positivo."
        )
    try:
        return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise TelemetryValidationError(
            f"Campo 'timestamp_coleta' fora do intervalo válido: {timestamp_ms}."
        ) from exc


def validate_and_map_packet(
    packet: telemetry_pb2.TelemetryPacket,
    metadata: Sequence[tuple[str, str | bytes]] | None = None,
) -> MappedTelemetry:
    """Valida contrato Protobuf e gera DTOs para PostgreSQL e tópico SNS."""
    packet_id = validate_packet_uuid(packet.message_id)

    boat_id = packet.boat_id.strip()
    if not boat_id:
        raise TelemetryValidationError("Campo 'boat_id' é obrigatório.")
    if len(boat_id) > MAX_BOAT_ID_LENGTH:
        raise TelemetryValidationError(
            f"Campo 'boat_id' excede o limite de {MAX_BOAT_ID_LENGTH} caracteres."
        )

    timestamp = _timestamp_ms_to_utc(packet.timestamp_coleta)

    if packet.passageiros < 0:
        raise TelemetryValidationError("Campo 'passageiros' não pode ser negativo.")

    if not packet.HasField("navegacao"):
        raise TelemetryValidationError("Campo obrigatório 'navegacao' ausente no pacote.")

    nav = packet.navegacao
    latitude = _require_finite(nav.latitude, "navegacao.latitude")
    longitude = _require_finite(nav.longitude, "navegacao.longitude")
    if not (-90.0 <= latitude <= 90.0):
        raise TelemetryValidationError(
            f"Campo 'navegacao.latitude' fora do intervalo [-90, 90]: {latitude}."
        )
    if not (-180.0 <= longitude <= 180.0):
        raise TelemetryValidationError(
            f"Campo 'navegacao.longitude' fora do intervalo [-180, 180]: {longitude}."
        )

    velocidade_nos = _require_finite(nav.velocidade_nos, "navegacao.velocidade_nos")
    if velocidade_nos < 0.0:
        raise TelemetryValidationError(
            f"Campo 'navegacao.velocidade_nos' não pode ser negativo: {velocidade_nos}."
        )

    rumo_graus = _require_finite(nav.rumo_graus, "navegacao.rumo_graus")
    if not (0.0 <= rumo_graus <= 360.0):
        raise TelemetryValidationError(
            f"Campo 'navegacao.rumo_graus' fora do intervalo [0, 360]: {rumo_graus}."
        )

    engine_rpm: float | None = None
    engine_temp: float | None = None
    fuel_level: float | None = None
    propulsao_dict: dict[str, Any] | None = None
    if packet.HasField("propulsao"):
        prop = packet.propulsao
        engine_rpm = _require_finite(prop.rpm_motor, "propulsao.rpm_motor")
        engine_temp = _require_finite(
            prop.temperatura_motor_celsius, "propulsao.temperatura_motor_celsius"
        )
        pressao_oleo = _require_finite(prop.pressao_oleo_bar, "propulsao.pressao_oleo_bar")
        fuel_level = _require_finite(
            prop.nivel_combustivel_percentual, "propulsao.nivel_combustivel_percentual"
        )
        consumo_lph = _require_finite(
            prop.consumo_instantaneo_lph, "propulsao.consumo_instantaneo_lph"
        )
        if engine_rpm < 0.0:
            raise TelemetryValidationError("Campo 'propulsao.rpm_motor' não pode ser negativo.")
        if not (0.0 <= fuel_level <= 100.0):
            raise TelemetryValidationError(
                "Campo 'propulsao.nivel_combustivel_percentual' deve estar entre 0 e 100."
            )
        propulsao_dict = {
            "rpm_motor": engine_rpm,
            "temperatura_motor_celsius": engine_temp,
            "pressao_oleo_bar": pressao_oleo,
            "nivel_combustivel_percentual": fuel_level,
            "consumo_instantaneo_lph": consumo_lph,
        }

    network_latency: float | None = None
    network_rssi: int | None = None
    rede_dict: dict[str, Any] | None = None
    if packet.HasField("rede"):
        rede = packet.rede
        network_latency = _require_finite(rede.latencia_rtt_ms, "rede.latencia_rtt_ms")
        perda_pct = _require_finite(
            rede.perda_pacotes_percentual, "rede.perda_pacotes_percentual"
        )
        if network_latency < 0.0:
            raise TelemetryValidationError("Campo 'rede.latencia_rtt_ms' não pode ser negativo.")
        if not (0.0 <= perda_pct <= 100.0):
            raise TelemetryValidationError(
                "Campo 'rede.perda_pacotes_percentual' deve estar entre 0 e 100."
            )
        network_rssi = int(rede.rssi_dbm)
        rede_dict = {
            "rssi_dbm": network_rssi,
            "latencia_rtt_ms": network_latency,
            "perda_pacotes_percentual": perda_pct,
            "tamanho_buffer_local": int(rede.tamanho_buffer_local),
            "tentativa_envio": int(rede.tentativa_envio),
        }

    try:
        nav_status_name = telemetry_pb2.NavigationStatus.Name(nav.status_navegacao)
    except ValueError as exc:
        raise TelemetryValidationError(
            f"Campo 'navegacao.status_navegacao' possui valor inválido: {nav.status_navegacao}."
        ) from exc

    if rede_dict is not None:
        try:
            rede_dict["tipo_enlace"] = telemetry_pb2.LinkType.Name(
                packet.rede.tipo_enlace
            )
        except ValueError as exc:
            raise TelemetryValidationError(
                f"Campo 'rede.tipo_enlace' possui valor inválido: {packet.rede.tipo_enlace}."
            ) from exc

    sequence_number = _extract_sequence_number(packet, metadata)

    record = TelemetryRecordInput(
        packet_id=packet_id,
        boat_id=boat_id,
        sequence_number=sequence_number,
        timestamp=timestamp,
        latitude=latitude,
        longitude=longitude,
        speed_knots=velocidade_nos,
        course_heading=rumo_graus,
        engine_rpm=engine_rpm,
        engine_temp_celsius=engine_temp,
        fuel_level_percent=fuel_level,
        network_latency_ms=network_latency,
        network_rssi_dbm=network_rssi,
    )

    sns_payload: dict[str, Any] = {
        "packet_id": str(packet_id),
        "message_id": str(packet_id),
        "boat_id": boat_id,
        "sequence_number": sequence_number,
        "timestamp_coleta": int(packet.timestamp_coleta),
        "timestamp": timestamp.isoformat(),
        "passageiros": int(packet.passageiros),
        "navegacao": {
            "latitude": latitude,
            "longitude": longitude,
            "velocidade_nos": velocidade_nos,
            "rumo_graus": rumo_graus,
            "status_navegacao": nav_status_name,
        },
        "propulsao": propulsao_dict,
        "rede": rede_dict,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    sns_attributes = {
        "packet_id": str(packet_id),
        "boat_id": boat_id,
        "status_navegacao": nav_status_name,
    }

    return MappedTelemetry(
        packet_id=packet_id,
        boat_id=boat_id,
        sequence_number=sequence_number,
        timestamp=timestamp,
        record=record,
        sns_payload=sns_payload,
        sns_attributes=sns_attributes,
    )

