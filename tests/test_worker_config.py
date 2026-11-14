"""Testes unitários de configuração do consumidor em lote WorkerSettings."""

from __future__ import annotations

import pytest

from src.worker.config import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_BATCH_TIMEOUT_SECONDS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_SQS_DLQ_URL,
    DEFAULT_SQS_QUEUE_URL,
    DEFAULT_WAIT_TIME_SECONDS,
    WorkerSettings,
)


def test_worker_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SQS_QUEUE_URL", raising=False)
    monkeypatch.delenv("SQS_DB_WRITER_QUEUE_URL", raising=False)
    monkeypatch.delenv("SQS_DLQ_URL", raising=False)
    monkeypatch.delenv("WORKER_BATCH_SIZE", raising=False)
    monkeypatch.delenv("WORKER_BATCH_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("SQS_WAIT_TIME_SECONDS", raising=False)
    monkeypatch.delenv("WORKER_MAX_RETRIES", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_HOST", raising=False)

    cfg = WorkerSettings.from_env()

    assert cfg.sqs_queue_url == DEFAULT_SQS_QUEUE_URL
    assert cfg.sqs_dlq_url == DEFAULT_SQS_DLQ_URL
    assert cfg.batch_size == DEFAULT_BATCH_SIZE
    assert cfg.batch_timeout_seconds == DEFAULT_BATCH_TIMEOUT_SECONDS
    assert cfg.wait_time_seconds == DEFAULT_WAIT_TIME_SECONDS
    assert cfg.max_retries == DEFAULT_MAX_RETRIES
    assert "postgresql+asyncpg://" in cfg.database_url


def test_worker_settings_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQS_QUEUE_URL", "http://sqs.custom/my-queue")
    monkeypatch.setenv("SQS_DLQ_URL", "http://sqs.custom/my-dlq")
    monkeypatch.setenv("WORKER_BATCH_SIZE", "25")
    monkeypatch.setenv("WORKER_BATCH_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("SQS_WAIT_TIME_SECONDS", "10")
    monkeypatch.setenv("WORKER_MAX_RETRIES", "5")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@remote:5432/custom_db",
    )

    cfg = WorkerSettings.from_env()

    assert cfg.sqs_queue_url == "http://sqs.custom/my-queue"
    assert cfg.sqs_dlq_url == "http://sqs.custom/my-dlq"
    assert cfg.batch_size == 25
    assert cfg.batch_timeout_seconds == 1.5
    assert cfg.wait_time_seconds == 10
    assert cfg.max_retries == 5
    assert cfg.database_url == "postgresql+asyncpg://user:pass@remote:5432/custom_db"

    db_cfg = cfg.to_database_settings()
    assert db_cfg.database_url == cfg.database_url


def test_worker_settings_constructs_db_url_from_host_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_HOST", "db.ferry.internal")
    monkeypatch.setenv("DB_PORT", "5433")
    monkeypatch.setenv("DB_NAME", "ferry_prod")
    monkeypatch.setenv("DB_USER", "postgres_admin")
    monkeypatch.setenv("DB_PASSWORD", "secret123")

    cfg = WorkerSettings.from_env()
    assert (
        cfg.database_url
        == "postgresql+asyncpg://postgres_admin:secret123@db.ferry.internal:5433/ferry_prod"
    )


@pytest.mark.parametrize(
    ("env_var", "invalid_value", "match_str"),
    [
        ("WORKER_BATCH_SIZE", "0", "WORKER_BATCH_SIZE deve ser maior que zero"),
        ("WORKER_BATCH_SIZE", "-5", "WORKER_BATCH_SIZE deve ser maior que zero"),
        ("WORKER_BATCH_TIMEOUT_SECONDS", "0", "WORKER_BATCH_TIMEOUT_SECONDS deve ser positivo"),
        ("WORKER_BATCH_TIMEOUT_SECONDS", "-1.5", "WORKER_BATCH_TIMEOUT_SECONDS deve ser positivo"),
        ("SQS_WAIT_TIME_SECONDS", "-1", "SQS_WAIT_TIME_SECONDS deve estar entre 0 e 20"),
        ("SQS_WAIT_TIME_SECONDS", "25", "SQS_WAIT_TIME_SECONDS deve estar entre 0 e 20"),
        ("WORKER_MAX_RETRIES", "0", "WORKER_MAX_RETRIES deve ser maior que zero"),
        ("WORKER_MAX_RETRIES", "-2", "WORKER_MAX_RETRIES deve ser maior que zero"),
    ],
)
def test_worker_settings_validations(
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
    invalid_value: str,
    match_str: str,
) -> None:
    monkeypatch.setenv(env_var, invalid_value)
    with pytest.raises(ValueError, match=match_str):
        WorkerSettings.from_env()
