"""Schemas Pydantic v2 para validação e serialização de dados da API REST."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TelemetryResponse(BaseModel):
    """Schema Pydantic v2 de um registro individual de telemetria náutica."""

    model_config = ConfigDict(from_attributes=True)

    packet_id: UUID = Field(..., description="Identificador único global do pacote (UUIDv4)")
    boat_id: str = Field(..., description="Identificador da embarcação")
    sequence_number: int = Field(..., description="Número sequencial monotônico do pacote")
    timestamp: datetime = Field(..., description="Momento exato da coleta em UTC")
    latitude: float = Field(..., description="Latitude GPS em graus decimais")
    longitude: float = Field(..., description="Longitude GPS em graus decimais")
    speed_knots: float | None = Field(default=None, description="Velocidade em nós")
    course_heading: float | None = Field(default=None, description="Proa/rumo magnético (0-360°)")
    hdop: float | None = Field(default=None, description="Diluição horizontal de precisão GPS")
    satellites_tracked: int | None = Field(default=None, description="Satélites GPS rastreados")
    engine_rpm: float | None = Field(default=None, description="Rotação do motor em RPM")
    engine_temp_celsius: float | None = Field(default=None, description="Temperatura do motor em °C")
    fuel_level_percent: float | None = Field(default=None, description="Nível de combustível em %")
    battery_voltage: float | None = Field(default=None, description="Tensão elétrica do banco de baterias em Volts")
    passengers: int | None = Field(default=None, description="Passageiros a bordo na leitura")
    network_latency_ms: float | None = Field(default=None, description="Latência de rede em ms")
    network_rssi_dbm: int | None = Field(default=None, description="Intensidade de sinal RSSI em dBm")
    created_at: datetime = Field(..., description="Timestamp de auditoria de ingestão no banco")


class HistoryPaginationResponse(BaseModel):
    """Envelope paginado de série temporal para traçado cartográfico de rotas."""

    boat_id: str = Field(..., description="Identificador da embarcação consultada")
    total: int = Field(..., description="Total de registros no período selecionado")
    limit: int = Field(..., description="Limite de registros por página")
    offset: int = Field(..., description="Deslocamento da paginação")
    items: list[TelemetryResponse] = Field(..., description="Lista ordenada de pacotes de telemetria")


AlertLevel = Literal["critical", "warning"]
BoatOperationalStatus = Literal["operational", "warning", "critical", "silent"]


class FleetAlert(BaseModel):
    """Alerta operacional detectado nas leituras da embarcação."""

    id: str = Field(..., description="Identificador da regra de alerta (ex: engine-temp, battery, fuel, stale)")
    boat_id: str = Field(..., description="Identificador da embarcação afetada")
    level: AlertLevel = Field(..., description="Gravidade do alerta")
    title: str = Field(..., description="Título descritivo do alerta")
    detail: str = Field(..., description="Mensagem de detalhe com valores medidos")
    timestamp: datetime = Field(..., description="Timestamp de ocorrência da leitura")


class BoatFleetSummary(BaseModel):
    """Sumário operacional individual de uma embarcação da frota."""

    boat_id: str = Field(..., description="Identificador da embarcação")
    status: BoatOperationalStatus = Field(..., description="Status operacional consolidado")
    last_contact: datetime | None = Field(default=None, description="Momento da última telemetria recebida")
    latest_telemetry: TelemetryResponse | None = Field(default=None, description="Leitura mais recente")
    avg_speed_knots: float | None = Field(default=None, description="Velocidade média registrada")
    total_packets: int = Field(default=0, description="Total de pacotes ingeridos na base")
    alerts: list[FleetAlert] = Field(default_factory=list, description="Alertas ativos para a embarcação")


class FleetMetricsResponse(BaseModel):
    """Sumário executivo da frota para monitoramento em tempo real."""

    total_boats: int = Field(..., description="Total de embarcações cadastradas/detectadas")
    active_boats: int = Field(..., description="Embarcações operando sem silêncio de rede")
    fleet_avg_speed_knots: float | None = Field(default=None, description="Velocidade média geral da frota em nós")
    boats: list[BoatFleetSummary] = Field(..., description="Status individual de cada embarcação")
    recent_alerts: list[FleetAlert] = Field(..., description="Lista de todos os alertas ativos na frota")
    generated_at: datetime = Field(..., description="Timestamp de geração do sumário em UTC")


class HealthResponse(BaseModel):
    """Status de saúde da API REST e conectividade com a base de dados."""

    status: str = Field("ok", description="Status da API")
    database: str = Field(..., description="Status de conectividade com o banco de dados")
    timestamp: datetime = Field(..., description="Timestamp UTC da checagem")
