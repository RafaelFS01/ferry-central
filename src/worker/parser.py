"""Módulo de validação e deserialização de mensagens SQS de telemetria náutica."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.database.repository import TelemetryRecordInput

MAX_BOAT_ID_LENGTH = 50


class CorruptedMessageError(ValueError):
    """Exceção levantada quando a mensagem SQS está corrompida ou fora do contrato."""


def _require_finite(val: Any, field_name: str) -> float:
    try:
        f = float(val)
    except (ValueError, TypeError) as exc:
        raise CorruptedMessageError(f"Campo '{field_name}' deve ser numérico: {val!r}") from exc
    if not math.isfinite(f):
        raise CorruptedMessageError(f"Campo '{field_name}' deve ser finito (recebido {val!r}).")
    return f


def _parse_timestamp(data: dict[str, Any]) -> datetime:
    ts_iso = data.get("timestamp")
    if ts_iso:
        if isinstance(ts_iso, datetime):
            if ts_iso.tzinfo is None:
                return ts_iso.replace(tzinfo=timezone.utc)
            return ts_iso.astimezone(timezone.utc)
        try:
            iso_str = str(ts_iso).strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception as exc:
            raise CorruptedMessageError(
                f"Formato de timestamp ISO 8601 inválido: {ts_iso!r}"
            ) from exc

    ts_coleta = data.get("timestamp_coleta")
    if ts_coleta is not None:
        try:
            epoch_ms = int(ts_coleta)
            if epoch_ms <= 0:
                raise ValueError("Epoch ms deve ser positivo")
            return datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
        except Exception as exc:
            raise CorruptedMessageError(
                f"Campo 'timestamp_coleta' Epoch ms inválido: {ts_coleta!r}"
            ) from exc

    raise CorruptedMessageError("Campos de data/hora ('timestamp' ou 'timestamp_coleta') ausentes.")


def parse_sqs_message(body: str | Mapping[str, Any]) -> TelemetryRecordInput:
    """Deserializa e valida carga útil SQS/SNS para TelemetryRecordInput.

    Levanta CorruptedMessageError caso o payload esteja malformado ou viole invariantes.
    """
    if isinstance(body, str):
        raw_text = body.strip()
        if not raw_text:
            raise CorruptedMessageError("Corpo da mensagem SQS está vazio.")
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise CorruptedMessageError(f"Payload JSON malformado: {exc}") from exc
    elif isinstance(body, Mapping):
        data = dict(body)
    else:
        raise CorruptedMessageError(f"Tipo de payload não suportado: {type(body).__name__}")

    if not isinstance(data, dict):
        raise CorruptedMessageError("Carga útil JSON deve ser um objeto/dicionário.")

    # Se a mensagem foi entregue via SNS sem RawMessageDelivery (envelope SNS padrão)
    if data.get("Type") == "Notification" and "Message" in data:
        inner = data["Message"]
        if isinstance(inner, str):
            try:
                data = json.loads(inner)
            except json.JSONDecodeError as exc:
                raise CorruptedMessageError(
                    f"Corpo interno 'Message' de notificação SNS malformado: {exc}"
                ) from exc
        elif isinstance(inner, dict):
            data = inner
        else:
            raise CorruptedMessageError("Corpo interno de notificação SNS não é um objeto.")

    if not isinstance(data, dict):
        raise CorruptedMessageError("Carga útil desempacotada deve ser um objeto/dicionário.")

    # Identificador do pacote (UUIDv4)
    raw_packet_id = data.get("packet_id") or data.get("message_id")
    if not raw_packet_id:
        raise CorruptedMessageError("Campo obrigatório 'packet_id' (ou 'message_id') ausente.")
    try:
        packet_id = UUID(str(raw_packet_id).strip())
    except Exception as exc:
        raise CorruptedMessageError(f"packet_id inválido como UUID: {raw_packet_id!r}") from exc

    # Identificador da embarcação
    boat_id = str(data.get("boat_id") or "").strip()
    if not boat_id:
        raise CorruptedMessageError("Campo obrigatório 'boat_id' ausente ou em branco.")
    if len(boat_id) > MAX_BOAT_ID_LENGTH:
        raise CorruptedMessageError(
            f"Campo 'boat_id' excede limite de {MAX_BOAT_ID_LENGTH} caracteres: {len(boat_id)}."
        )

    # Número sequencial
    seq_raw = data.get("sequence_number")
    if seq_raw is None:
        seq_raw = data.get("timestamp_coleta", 0)
    try:
        sequence_number = int(seq_raw)
    except (ValueError, TypeError) as exc:
        raise CorruptedMessageError(f"Campo 'sequence_number' inválido: {seq_raw!r}") from exc
    if sequence_number < 0:
        raise CorruptedMessageError(
            f"Campo 'sequence_number' não pode ser negativo: {sequence_number}."
        )

    # Timestamp de coleta
    timestamp = _parse_timestamp(data)

    # Navegação / Coordenadas GPS (suporta formato aninhado 'navegacao' ou chaves no nível raiz)
    nav = data.get("navegacao")
    if isinstance(nav, dict):
        raw_lat = nav.get("latitude")
        raw_lon = nav.get("longitude")
        raw_speed = nav.get("velocidade_nos")
        raw_heading = nav.get("rumo_graus")
        raw_hdop = nav.get("hdop", data.get("hdop"))
        raw_satellites = nav.get("satellites_tracked", data.get("satellites_tracked"))
    else:
        raw_lat = data.get("latitude")
        raw_lon = data.get("longitude")
        raw_speed = data.get("speed_knots")
        raw_heading = data.get("course_heading")
        raw_hdop = data.get("hdop")
        raw_satellites = data.get("satellites_tracked")

    if raw_lat is None or raw_lon is None:
        raise CorruptedMessageError("Campos de coordenadas GPS ('latitude', 'longitude') obrigatórios.")

    lat = _require_finite(raw_lat, "latitude")
    lon = _require_finite(raw_lon, "longitude")
    if not (-90.0 <= lat <= 90.0):
        raise CorruptedMessageError(f"Campo 'latitude' fora do intervalo [-90, 90]: {lat}.")
    if not (-180.0 <= lon <= 180.0):
        raise CorruptedMessageError(f"Campo 'longitude' fora do intervalo [-180, 180]: {lon}.")

    speed_knots: float | None = None
    if raw_speed is not None:
        speed_knots = _require_finite(raw_speed, "speed_knots/velocidade_nos")
        if speed_knots < 0.0:
            raise CorruptedMessageError(f"Velocidade náutica não pode ser negativa: {speed_knots}.")

    course_heading: float | None = None
    if raw_heading is not None:
        course_heading = _require_finite(raw_heading, "course_heading/rumo_graus")
        if not (0.0 <= course_heading <= 360.0):
            raise CorruptedMessageError(f"Rumo em graus fora do intervalo [0, 360]: {course_heading}.")

    hdop: float | None = None
    if raw_hdop is not None:
        hdop = _require_finite(raw_hdop, "hdop")

    satellites_tracked: int | None = None
    if raw_satellites is not None:
        try:
            satellites_tracked = int(raw_satellites)
            if satellites_tracked < 0:
                raise ValueError()
        except Exception as exc:
            raise CorruptedMessageError(f"satellites_tracked inválido: {raw_satellites!r}") from exc

    # Propulsão náutica (aninhada ou plana)
    prop = data.get("propulsao")
    if isinstance(prop, dict):
        raw_rpm = prop.get("rpm_motor")
        raw_temp = prop.get("temperatura_motor_celsius")
        raw_fuel = prop.get("nivel_combustivel_percentual")
    else:
        raw_rpm = data.get("engine_rpm")
        raw_temp = data.get("engine_temp_celsius")
        raw_fuel = data.get("fuel_level_percent")

    engine_rpm: float | None = None
    if raw_rpm is not None:
        engine_rpm = _require_finite(raw_rpm, "engine_rpm/rpm_motor")
        if engine_rpm < 0.0:
            raise CorruptedMessageError(f"RPM do motor não pode ser negativo: {engine_rpm}.")

    engine_temp_celsius: float | None = None
    if raw_temp is not None:
        engine_temp_celsius = _require_finite(raw_temp, "engine_temp_celsius")

    fuel_level_percent: float | None = None
    if raw_fuel is not None:
        fuel_level_percent = _require_finite(raw_fuel, "fuel_level_percent")
        if not (0.0 <= fuel_level_percent <= 100.0):
            raise CorruptedMessageError(
                f"Nível de combustível percentual fora de [0, 100]: {fuel_level_percent}."
            )

    raw_voltage = data.get("battery_voltage")
    battery_voltage: float | None = None
    if raw_voltage is not None:
        battery_voltage = _require_finite(raw_voltage, "battery_voltage")

    # Diagnóstico de rede (aninhado ou plano)
    rede = data.get("rede")
    if isinstance(rede, dict):
        raw_latency = rede.get("latencia_rtt_ms")
        raw_rssi = rede.get("rssi_dbm")
    else:
        raw_latency = data.get("network_latency_ms")
        raw_rssi = data.get("network_rssi_dbm")

    network_latency_ms: float | None = None
    if raw_latency is not None:
        network_latency_ms = _require_finite(raw_latency, "network_latency_ms/latencia_rtt_ms")
        if network_latency_ms < 0.0:
            raise CorruptedMessageError(
                f"Latência de rede não pode ser negativa: {network_latency_ms}."
            )

    network_rssi_dbm: int | None = None
    if raw_rssi is not None:
        try:
            network_rssi_dbm = int(raw_rssi)
        except Exception as exc:
            raise CorruptedMessageError(f"RSSI de rede inválido: {raw_rssi!r}") from exc

    return TelemetryRecordInput(
        packet_id=packet_id,
        boat_id=boat_id,
        sequence_number=sequence_number,
        timestamp=timestamp,
        latitude=lat,
        longitude=lon,
        speed_knots=speed_knots,
        course_heading=course_heading,
        hdop=hdop,
        satellites_tracked=satellites_tracked,
        engine_rpm=engine_rpm,
        engine_temp_celsius=engine_temp_celsius,
        fuel_level_percent=fuel_level_percent,
        battery_voltage=battery_voltage,
        network_latency_ms=network_latency_ms,
        network_rssi_dbm=network_rssi_dbm,
    )
