"""Testes de integração ponta a ponta do TelemetryBatchWorker com PostgreSQL 18 e LocalStack SQS."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.database import (
    DatabaseSettings,
    Telemetry,
    create_async_db_engine,
    create_session_factory,
)
from src.worker.config import WorkerSettings
from src.worker.consumer import TelemetryBatchWorker
from src.worker.sqs_client import BotoSqsClient


@pytest.fixture
async def integration_env() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession], BotoSqsClient, WorkerSettings]:
    db_url = os.getenv("DATABASE_URL")
    endpoint_url = os.getenv("AWS_ENDPOINT_URL")
    if not db_url or not endpoint_url:
        pytest.skip("DATABASE_URL e AWS_ENDPOINT_URL necessárias para testes de integração.")

    settings = WorkerSettings(
        sqs_queue_url=f"{endpoint_url}/000000000000/ferry-db-writer-queue",
        sqs_dlq_url=f"{endpoint_url}/000000000000/ferry-db-writer-queue-dlq",
        batch_size=50,
        batch_timeout_seconds=0.5,
        wait_time_seconds=1,
        max_retries=3,
        aws_region="us-east-1",
        aws_endpoint_url=endpoint_url,
        database_url=db_url,
    )

    db_settings = DatabaseSettings.from_env()
    engine = create_async_db_engine(db_settings)
    session_factory = create_session_factory(engine)
    sqs_client = BotoSqsClient(
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    )

    try:
        yield engine, session_factory, sqs_client, settings
    finally:
        await sqs_client.close()
        await engine.dispose()


async def test_worker_end_to_end_sqs_to_postgres(
    integration_env: tuple[AsyncEngine, async_sessionmaker[AsyncSession], BotoSqsClient, WorkerSettings],
) -> None:
    engine, session_factory, sqs_client, settings = integration_env

    packet_id_1 = str(uuid4())
    packet_id_2 = str(uuid4())

    msg_payload_1 = {
        "packet_id": packet_id_1,
        "boat_id": "ferry-ivete-sangalo",
        "sequence_number": 501,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "navegacao": {
            "latitude": -12.9715,
            "longitude": -38.5015,
            "velocidade_nos": 15.2,
            "rumo_graus": 210.0,
        },
        "propulsao": {
            "rpm_motor": 1750.0,
            "temperatura_motor_celsius": 80.0,
            "nivel_combustivel_percentual": 65.0,
        },
    }

    msg_payload_2 = {
        "packet_id": packet_id_2,
        "boat_id": "ferry-ivete-sangalo",
        "sequence_number": 502,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "navegacao": {
            "latitude": -12.9720,
            "longitude": -38.5020,
            "velocidade_nos": 15.5,
            "rumo_graus": 211.0,
        },
    }

    # Publica na fila SQS
    await sqs_client.send_message(settings.sqs_queue_url, json.dumps(msg_payload_1))
    await sqs_client.send_message(settings.sqs_queue_url, json.dumps(msg_payload_2))

    worker = TelemetryBatchWorker(
        settings=settings,
        session_factory=session_factory,
        sqs_client=sqs_client,
    )

    inserted = await worker.process_one_batch()
    assert inserted >= 2

    # Verifica persistência no PostgreSQL
    async with session_factory() as session:
        stmt = select(Telemetry).where(
            Telemetry.packet_id.in_([UUID(packet_id_1), UUID(packet_id_2)])
        )
        result = await session.scalars(stmt)
        rows = list(result.all())
        assert len(rows) == 2
        pids = {str(row.packet_id) for row in rows}
        assert packet_id_1 in pids
        assert packet_id_2 in pids
