"""Configuração do servidor gRPC assíncrono de ingestão de telemetria."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

DEFAULT_GRPC_HOST = "[::]"
DEFAULT_GRPC_PORT = 50051
DEFAULT_SNS_TOPIC_NAME = "ferry-telemetry-topic"
DEFAULT_AWS_REGION = "us-east-1"
DEFAULT_IDEMPOTENCY_CACHE_SIZE = 50_000
DEFAULT_IDEMPOTENCY_CACHE_TTL_SECONDS = 3600.0
DEFAULT_SHUTDOWN_GRACE_SECONDS = 10.0
DEFAULT_MAX_MESSAGE_LENGTH_BYTES = 4 * 1024 * 1024


class IngestionMode(StrEnum):
    """Modos suportados para o pipeline de ingestão da Central."""

    AUTO = "auto"
    DIRECT = "direct"
    DECOUPLED = "decoupled"
    BOTH = "both"


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


@dataclass(frozen=True, slots=True)
class ServerSettings:
    """Parâmetros de rede, idempotência, PostgreSQL (Direct) e SNS (Decoupled)."""

    grpc_host: str = DEFAULT_GRPC_HOST
    grpc_port: int = DEFAULT_GRPC_PORT
    ingestion_mode: IngestionMode = IngestionMode.AUTO
    direct_path_enabled: bool = True
    decoupled_path_enabled: bool = False
    sns_topic_arn: str | None = None
    sns_topic_name: str = DEFAULT_SNS_TOPIC_NAME
    aws_region: str = DEFAULT_AWS_REGION
    aws_endpoint_url: str | None = None
    idempotency_cache_size: int = DEFAULT_IDEMPOTENCY_CACHE_SIZE
    idempotency_cache_ttl_seconds: float = DEFAULT_IDEMPOTENCY_CACHE_TTL_SECONDS
    shutdown_grace_seconds: float = DEFAULT_SHUTDOWN_GRACE_SECONDS
    max_message_length_bytes: int = DEFAULT_MAX_MESSAGE_LENGTH_BYTES
    log_level: str = "INFO"

    @property
    def bind_address(self) -> str:
        """Endereço completo de bind do servidor gRPC."""
        return f"{self.grpc_host}:{self.grpc_port}"

    @classmethod
    def from_env(cls) -> ServerSettings:
        """Carrega configurações do servidor a partir de variáveis de ambiente."""
        raw_mode = os.getenv("INGESTION_MODE", IngestionMode.AUTO.value).strip().lower()
        try:
            mode = IngestionMode(raw_mode)
        except ValueError as exc:
            valid = ", ".join(m.value for m in IngestionMode)
            raise ValueError(
                f"INGESTION_MODE inválido: {raw_mode!r}. Valores aceitos: {valid}."
            ) from exc

        sns_topic_arn = _parse_optional_str(os.getenv("SNS_TOPIC_ARN"))
        sns_topic_name = (
            _parse_optional_str(os.getenv("SNS_TOPIC_NAME")) or DEFAULT_SNS_TOPIC_NAME
        )

        if mode is IngestionMode.DIRECT:
            direct_enabled = True
            decoupled_enabled = False
        elif mode is IngestionMode.DECOUPLED:
            direct_enabled = False
            decoupled_enabled = True
        elif mode is IngestionMode.BOTH:
            direct_enabled = True
            decoupled_enabled = True
        else:
            direct_enabled = _parse_bool(os.getenv("DIRECT_PATH_ENABLED"), True)
            sns_configured = bool(
                sns_topic_arn or _parse_optional_str(os.getenv("SNS_TOPIC_NAME"))
            )
            decoupled_enabled = _parse_bool(os.getenv("SNS_ENABLED"), sns_configured)

        grpc_port = int(os.getenv("GRPC_PORT", str(DEFAULT_GRPC_PORT)))
        if not (1 <= grpc_port <= 65535):
            raise ValueError(f"GRPC_PORT fora do intervalo válido (1-65535): {grpc_port}")

        cache_size = int(
            os.getenv("IDEMPOTENCY_CACHE_SIZE", str(DEFAULT_IDEMPOTENCY_CACHE_SIZE))
        )
        if cache_size < 0:
            raise ValueError("IDEMPOTENCY_CACHE_SIZE não pode ser negativo.")

        cache_ttl = float(
            os.getenv(
                "IDEMPOTENCY_CACHE_TTL_SECONDS",
                str(DEFAULT_IDEMPOTENCY_CACHE_TTL_SECONDS),
            )
        )
        if cache_ttl < 0:
            raise ValueError("IDEMPOTENCY_CACHE_TTL_SECONDS não pode ser negativo.")

        shutdown_grace_seconds = float(
            os.getenv(
                "GRPC_SHUTDOWN_GRACE_SECONDS",
                str(DEFAULT_SHUTDOWN_GRACE_SECONDS),
            )
        )
        if shutdown_grace_seconds < 0:
            raise ValueError("GRPC_SHUTDOWN_GRACE_SECONDS não pode ser negativo.")

        max_message_length_bytes = int(
            os.getenv(
                "GRPC_MAX_MESSAGE_LENGTH_BYTES",
                str(DEFAULT_MAX_MESSAGE_LENGTH_BYTES),
            )
        )
        if max_message_length_bytes <= 0:
            raise ValueError("GRPC_MAX_MESSAGE_LENGTH_BYTES deve ser maior que zero.")

        return cls(
            grpc_host=_parse_optional_str(os.getenv("GRPC_HOST")) or DEFAULT_GRPC_HOST,
            grpc_port=grpc_port,
            ingestion_mode=mode,
            direct_path_enabled=direct_enabled,
            decoupled_path_enabled=decoupled_enabled,
            sns_topic_arn=sns_topic_arn,
            sns_topic_name=sns_topic_name,
            aws_region=(
                _parse_optional_str(os.getenv("AWS_REGION"))
                or _parse_optional_str(os.getenv("AWS_DEFAULT_REGION"))
                or DEFAULT_AWS_REGION
            ),
            aws_endpoint_url=_parse_optional_str(os.getenv("AWS_ENDPOINT_URL")),
            idempotency_cache_size=cache_size,
            idempotency_cache_ttl_seconds=cache_ttl,
            shutdown_grace_seconds=shutdown_grace_seconds,
            max_message_length_bytes=max_message_length_bytes,
            log_level=(_parse_optional_str(os.getenv("LOG_LEVEL")) or "INFO").upper(),
        )

