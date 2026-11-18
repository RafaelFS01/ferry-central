"""Configurações operacionais da API REST interna da Central."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_API_HOST = "0.0.0.0"
DEFAULT_API_PORT = 8000
DEFAULT_STALE_THRESHOLD_SECONDS = 30.0
DEFAULT_ENGINE_TEMP_WARNING = 88.0
DEFAULT_ENGINE_TEMP_CRITICAL = 90.0
DEFAULT_BATTERY_LOW_VOLTAGE = 23.5
DEFAULT_FUEL_LOW_PERCENT = 15.0


def _parse_origins(val: str | None) -> list[str]:
    if not val or not val.strip():
        return ["*"]
    return [origin.strip() for origin in val.split(",") if origin.strip()]


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Parâmetros de execução da API REST e thresholds operacionais de alerta."""

    api_host: str = DEFAULT_API_HOST
    api_port: int = DEFAULT_API_PORT
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    stale_threshold_seconds: float = DEFAULT_STALE_THRESHOLD_SECONDS
    engine_temp_warning_celsius: float = DEFAULT_ENGINE_TEMP_WARNING
    engine_temp_critical_celsius: float = DEFAULT_ENGINE_TEMP_CRITICAL
    battery_voltage_warning: float = DEFAULT_BATTERY_LOW_VOLTAGE
    fuel_level_warning_percent: float = DEFAULT_FUEL_LOW_PERCENT
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> ApiSettings:
        """Inicializa configurações a partir das variáveis de ambiente."""
        host = os.getenv("API_HOST", os.getenv("REST_HOST", DEFAULT_API_HOST)).strip()
        port_raw = os.getenv("API_PORT", os.getenv("REST_PORT", str(DEFAULT_API_PORT)))
        try:
            port = int(port_raw)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            raise ValueError(f"Porta da API REST inválida: {port_raw}")

        return cls(
            api_host=host,
            api_port=port,
            cors_origins=_parse_origins(os.getenv("CORS_ORIGINS")),
            stale_threshold_seconds=float(
                os.getenv("STALE_THRESHOLD_SECONDS", str(DEFAULT_STALE_THRESHOLD_SECONDS))
            ),
            engine_temp_warning_celsius=float(
                os.getenv("ENGINE_TEMP_WARNING_CELSIUS", str(DEFAULT_ENGINE_TEMP_WARNING))
            ),
            engine_temp_critical_celsius=float(
                os.getenv("ENGINE_TEMP_CRITICAL_CELSIUS", str(DEFAULT_ENGINE_TEMP_CRITICAL))
            ),
            battery_voltage_warning=float(
                os.getenv("BATTERY_VOLTAGE_WARNING", str(DEFAULT_BATTERY_LOW_VOLTAGE))
            ),
            fuel_level_warning_percent=float(
                os.getenv("FUEL_LEVEL_WARNING_PERCENT", str(DEFAULT_FUEL_LOW_PERCENT))
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip(),
        )
