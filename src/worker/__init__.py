"""Módulo de processamento assíncrono e persistência em lote via SQS (SCRUM-17)."""

from __future__ import annotations

from src.worker.config import WorkerSettings
from src.worker.consumer import TelemetryBatchWorker
from src.worker.parser import CorruptedMessageError, parse_sqs_message
from src.worker.sqs_client import BotoSqsClient, SqsClientProtocol

__all__ = [
    "BotoSqsClient",
    "CorruptedMessageError",
    "SqsClientProtocol",
    "TelemetryBatchWorker",
    "WorkerSettings",
    "parse_sqs_message",
]
