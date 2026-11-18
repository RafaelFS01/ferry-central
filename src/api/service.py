"""Serviço de cálculo de métricas agregadas da frota e avaliação de alertas operacionais."""

from __future__ import annotations

from datetime import datetime, timezone

from src.api.config import ApiSettings
from src.api.schemas import (
    BoatFleetSummary,
    BoatOperationalStatus,
    FleetAlert,
    FleetMetricsResponse,
    TelemetryResponse,
)
from src.database.models import Telemetry
from src.database.repository import TelemetryRepository


def evaluate_telemetry_alerts(
    telemetry: Telemetry | None,
    now: datetime,
    settings: ApiSettings,
) -> tuple[BoatOperationalStatus, list[FleetAlert]]:
    """Avalia o registro mais recente contra limites náuticos para emitir alertas e status."""
    if telemetry is None:
        return "silent", []

    alerts: list[FleetAlert] = []
    ts = telemetry.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)

    # 1. Alerta de superaquecimento ou temperatura elevada do motor
    if telemetry.engine_temp_celsius is not None:
        if telemetry.engine_temp_celsius > settings.engine_temp_critical_celsius:
            alerts.append(
                FleetAlert(
                    id="engine-temp",
                    boat_id=telemetry.boat_id,
                    level="critical",
                    title="Superaquecimento do motor",
                    detail=f"{telemetry.engine_temp_celsius:.1f} °C — acima de {settings.engine_temp_critical_celsius:.1f} °C",
                    timestamp=ts,
                )
            )
        elif telemetry.engine_temp_celsius >= settings.engine_temp_warning_celsius:
            alerts.append(
                FleetAlert(
                    id="engine-temp",
                    boat_id=telemetry.boat_id,
                    level="warning",
                    title="Temperatura do motor elevada",
                    detail=f"{telemetry.engine_temp_celsius:.1f} °C — próximo do limite operacional",
                    timestamp=ts,
                )
            )

    # 2. Alerta de tensão baixa de bateria
    if telemetry.battery_voltage is not None:
        if telemetry.battery_voltage < settings.battery_voltage_warning:
            alerts.append(
                FleetAlert(
                    id="battery",
                    boat_id=telemetry.boat_id,
                    level="warning",
                    title="Tensão de bateria baixa",
                    detail=f"{telemetry.battery_voltage:.1f} V — abaixo de {settings.battery_voltage_warning:.1f} V",
                    timestamp=ts,
                )
            )

    # 3. Alerta de combustível baixo
    if telemetry.fuel_level_percent is not None:
        if telemetry.fuel_level_percent < settings.fuel_level_warning_percent:
            alerts.append(
                FleetAlert(
                    id="fuel",
                    boat_id=telemetry.boat_id,
                    level="warning",
                    title="Combustível baixo",
                    detail=f"{telemetry.fuel_level_percent:.0f}% no tanque — abaixo de {settings.fuel_level_warning_percent:.0f}%",
                    timestamp=ts,
                )
            )

    # 4. Alerta de silêncio de telemetria / partição de rede
    silence_seconds = (now - ts).total_seconds()
    is_silent = silence_seconds > settings.stale_threshold_seconds
    if is_silent:
        alerts.append(
            FleetAlert(
                id="stale",
                boat_id=telemetry.boat_id,
                level="critical",
                title="Sem telemetria recente",
                detail=f"Última leitura há {int(silence_seconds)}s — possível partição de rede",
                timestamp=ts,
            )
        )

    # Ordenação por prioridade: critical primeiro
    alerts.sort(key=lambda a: 0 if a.level == "critical" else 1)

    # Determinação do status operacional
    if is_silent:
        status: BoatOperationalStatus = "silent"
    elif any(a.level == "critical" for a in alerts):
        status = "critical"
    elif any(a.level == "warning" for a in alerts):
        status = "warning"
    else:
        status = "operational"

    return status, alerts


class FleetMetricsService:
    """Orquestrador de consultas agregadas e sumário da frota."""

    def __init__(self, repository: TelemetryRepository, settings: ApiSettings) -> None:
        self._repo = repository
        self._settings = settings

    async def get_fleet_summary(self, now: datetime | None = None) -> FleetMetricsResponse:
        """Gera o sumário completo da frota de embarcações."""
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)

        boat_ids = await self._repo.list_distinct_boats()
        fleet_avg_speed = await self._repo.get_fleet_avg_speed()

        boat_summaries: list[BoatFleetSummary] = []
        all_recent_alerts: list[FleetAlert] = []
        active_boats_count = 0

        for boat_id in boat_ids:
            latest = await self._repo.get_latest_by_boat(boat_id)
            stats = await self._repo.get_boat_stats(boat_id)
            status, alerts = evaluate_telemetry_alerts(latest, current_time, self._settings)

            if status != "silent":
                active_boats_count += 1

            all_recent_alerts.extend(alerts)

            latest_resp = TelemetryResponse.model_validate(latest) if latest is not None else None
            last_contact = latest.timestamp if latest is not None else None

            boat_summaries.append(
                BoatFleetSummary(
                    boat_id=boat_id,
                    status=status,
                    last_contact=last_contact,
                    latest_telemetry=latest_resp,
                    avg_speed_knots=stats["avg_speed"],
                    total_packets=stats["total_packets"],
                    alerts=alerts,
                )
            )

        # Ordena alertas gerais da frota por nível crítico e recência
        all_recent_alerts.sort(
            key=lambda a: (0 if a.level == "critical" else 1, -a.timestamp.timestamp())
        )

        return FleetMetricsResponse(
            total_boats=len(boat_ids),
            active_boats=active_boats_count,
            fleet_avg_speed_knots=fleet_avg_speed,
            boats=boat_summaries,
            recent_alerts=all_recent_alerts,
            generated_at=current_time,
        )
