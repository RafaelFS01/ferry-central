"""Modelos relacionais SQLAlchemy 2.0 para persistência de telemetria marítima."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Double, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class Telemetry(Base):
    """Registro de pacote de telemetria náutica recebido de uma embarcação."""

    __tablename__ = "telemetria"

    packet_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
    )
    boat_id: Mapped[str] = mapped_column(String(50), nullable=False)
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Coordenadas e cinemática GPS
    latitude: Mapped[float] = mapped_column(Double, nullable=False)
    longitude: Mapped[float] = mapped_column(Double, nullable=False)
    speed_knots: Mapped[float | None] = mapped_column(Double, nullable=True)
    course_heading: Mapped[float | None] = mapped_column(Double, nullable=True)
    hdop: Mapped[float | None] = mapped_column(Double, nullable=True)
    satellites_tracked: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Propulsão e energia
    engine_rpm: Mapped[float | None] = mapped_column(Double, nullable=True)
    engine_temp_celsius: Mapped[float | None] = mapped_column(Double, nullable=True)
    fuel_level_percent: Mapped[float | None] = mapped_column(Double, nullable=True)
    battery_voltage: Mapped[float | None] = mapped_column(Double, nullable=True)

    # Métricas de rede
    network_latency_ms: Mapped[float | None] = mapped_column(Double, nullable=True)
    network_rssi_dbm: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Auditoria de ingestão em UTC
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_telemetria_boat_timestamp", boat_id, timestamp.desc()),
        Index("idx_telemetria_packet_id", packet_id, unique=True),
    )

    def __repr__(self) -> str:
        return (
            f"Telemetry(packet_id={self.packet_id!r}, boat_id={self.boat_id!r}, "
            f"sequence_number={self.sequence_number!r}, timestamp={self.timestamp!r})"
        )

