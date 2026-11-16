"""Configurações do serviço consumidor assíncrono em lote SQS -> PostgreSQL."""

from __future__ import annotations

import os
from dataclasses import dataclass

from src.database.config import (
    DEFAULT_LOCAL_DATABASE_URL,
    DatabaseSettings,
    normalize_async_database_url,
)

DEFAULT_QUEUE_NAME = "ferry-db-writer-queue"
DEFAULT_DLQ_NAME = "ferry-db-writer-queue-dlq"
DEFAULT_LOCAL_ENDPOINT_URL = "http://localhost:4566"
DEFAULT_LOCALSTACK_ACCOUNT_ID = "000000000000"

DEFAULT_SQS_QUEUE_URL = (
    f"{DEFAULT_LOCAL_ENDPOINT_URL}/{DEFAULT_LOCALSTACK_ACCOUNT_ID}/{DEFAULT_QUEUE_NAME}"
)
DEFAULT_SQS_DLQ_URL = (
    f"{DEFAULT_LOCAL_ENDPOINT_URL}/{DEFAULT_LOCALSTACK_ACCOUNT_ID}/{DEFAULT_DLQ_NAME}"
)
DEFAULT_BATCH_SIZE = 50
DEFAULT_BATCH_TIMEOUT_SECONDS = 2.0
DEFAULT_WAIT_TIME_SECONDS = 20
DEFAULT_MAX_RETRIES = 3
DEFAULT_AWS_REGION = "us-east-1"
DEFAULT_SHUTDOWN_GRACE_SECONDS = 10.0


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
class WorkerSettings:
    """Parâmetros operacionais do worker consumidor SQS em lote."""

    sqs_queue_url: str = DEFAULT_SQS_QUEUE_URL
    sqs_dlq_url: str | None = DEFAULT_SQS_DLQ_URL
    batch_size: int = DEFAULT_BATCH_SIZE
    batch_timeout_seconds: float = DEFAULT_BATCH_TIMEOUT_SECONDS
    wait_time_seconds: int = DEFAULT_WAIT_TIME_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    aws_region: str = DEFAULT_AWS_REGION
    aws_endpoint_url: str | None = None
    database_url: str = DEFAULT_LOCAL_DATABASE_URL
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: float = 30.0
    shutdown_grace_seconds: float = DEFAULT_SHUTDOWN_GRACE_SECONDS
    log_level: str = "INFO"

    def to_database_settings(self) -> DatabaseSettings:
        """Converte configurações de banco de dados para a estrutura nativa."""
        return DatabaseSettings(
            database_url=normalize_async_database_url(self.database_url),
            pool_size=self.db_pool_size,
            max_overflow=self.db_max_overflow,
            pool_timeout=self.db_pool_timeout,
        )


    @classmethod
    def from_env(cls) -> WorkerSettings:
        """Carrega e valida configurações do consumidor a partir das variáveis de ambiente."""
        aws_endpoint = _parse_optional_str(os.getenv("AWS_ENDPOINT_URL"))
        base_endpoint = aws_endpoint.rstrip("/") if aws_endpoint else DEFAULT_LOCAL_ENDPOINT_URL

        queue_url = (
            _parse_optional_str(os.getenv("SQS_QUEUE_URL"))
            or _parse_optional_str(os.getenv("SQS_DB_WRITER_QUEUE_URL"))
            or f"{base_endpoint}/{DEFAULT_LOCALSTACK_ACCOUNT_ID}/{DEFAULT_QUEUE_NAME}"
        )

        dlq_url = (
            _parse_optional_str(os.getenv("SQS_DLQ_URL"))
            or (f"{queue_url}-dlq" if queue_url and not queue_url.endswith("-dlq") else None)
            or f"{base_endpoint}/{DEFAULT_LOCALSTACK_ACCOUNT_ID}/{DEFAULT_DLQ_NAME}"
        )

        batch_size = int(os.getenv("WORKER_BATCH_SIZE", str(DEFAULT_BATCH_SIZE)))
        if batch_size <= 0:
            raise ValueError(f"WORKER_BATCH_SIZE deve ser maior que zero (recebido {batch_size}).")

        batch_timeout = float(
            os.getenv("WORKER_BATCH_TIMEOUT_SECONDS", str(DEFAULT_BATCH_TIMEOUT_SECONDS))
        )
        if batch_timeout <= 0.0:
            raise ValueError(
                f"WORKER_BATCH_TIMEOUT_SECONDS deve ser positivo (recebido {batch_timeout})."
            )

        wait_time = int(os.getenv("SQS_WAIT_TIME_SECONDS", str(DEFAULT_WAIT_TIME_SECONDS)))
        if not (0 <= wait_time <= 20):
            raise ValueError(
                f"SQS_WAIT_TIME_SECONDS deve estar entre 0 e 20 segundos (recebido {wait_time})."
            )

        max_retries = int(
            os.getenv(
                "WORKER_MAX_RETRIES",
                os.getenv("SQS_MAX_RECEIVE_COUNT", str(DEFAULT_MAX_RETRIES)),
            )
        )
        if max_retries <= 0:
            raise ValueError(f"WORKER_MAX_RETRIES deve ser maior que zero (recebido {max_retries}).")

        # Resolução de URL de conexão ao PostgreSQL
        raw_db_url = _parse_optional_str(os.getenv("DATABASE_URL"))
        if not raw_db_url:
            db_host = _parse_optional_str(os.getenv("DB_HOST"))
            if db_host:
                db_port = os.getenv("DB_PORT", "5432")
                db_name = os.getenv("DB_NAME", "ferry_telemetry")
                db_user = os.getenv("DB_USER", "ferry")
                db_password = os.getenv("DB_PASSWORD", "ferry_local")
                raw_db_url = (
                    f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
                )
            else:
                raw_db_url = DEFAULT_LOCAL_DATABASE_URL

        db_url = normalize_async_database_url(raw_db_url)

        shutdown_grace = float(
            os.getenv("WORKER_SHUTDOWN_GRACE_SECONDS", str(DEFAULT_SHUTDOWN_GRACE_SECONDS))
        )
        if shutdown_grace < 0.0:
            raise ValueError("WORKER_SHUTDOWN_GRACE_SECONDS não pode ser negativo.")

        return cls(
            sqs_queue_url=queue_url,
            sqs_dlq_url=dlq_url,
            batch_size=batch_size,
            batch_timeout_seconds=batch_timeout,
            wait_time_seconds=wait_time,
            max_retries=max_retries,
            aws_region=(
                _parse_optional_str(os.getenv("AWS_REGION"))
                or _parse_optional_str(os.getenv("AWS_DEFAULT_REGION"))
                or DEFAULT_AWS_REGION
            ),
            aws_endpoint_url=_parse_optional_str(os.getenv("AWS_ENDPOINT_URL")),
            database_url=db_url,
            db_pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
            db_max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
            db_pool_timeout=float(os.getenv("DB_POOL_TIMEOUT", "30.0")),
            shutdown_grace_seconds=shutdown_grace,
            log_level=(_parse_optional_str(os.getenv("LOG_LEVEL")) or "INFO").upper(),
        )
