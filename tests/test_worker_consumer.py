"""Testes unitários e comportamentais do consumidor em lote TelemetryBatchWorker."""

from __future__ import annotations

import json
from collections.abc import Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from src.database.repository import TelemetryRecordInput
from src.worker.config import WorkerSettings
from src.worker.consumer import TelemetryBatchWorker


class _MockSqsClient:
    """Simulador de fila SQS em memória para testes de ciclo de vida do worker."""

    def __init__(self, message_batches: list[list[dict[str, Any]]] | None = None) -> None:
        self.message_batches = list(message_batches or [])
        self.deleted_handles: list[str] = []
        self.visibility_changes: list[tuple[str, int]] = []
        self.dlq_messages: list[dict[str, Any]] = []
        self.receive_calls: int = 0
        self.closed: bool = False

    async def receive_messages(
        self,
        queue_url: str,
        max_number: int = 10,
        wait_time_seconds: int = 20,
    ) -> list[dict[str, Any]]:
        self.receive_calls += 1
        if self.message_batches:
            batch = self.message_batches.pop(0)
            return batch[:max_number]
        # Se não há mais lotes pré-programados, simula ausência de mensagens
        return []

    async def delete_messages_batch(
        self,
        queue_url: str,
        receipt_handles: Sequence[str],
    ) -> None:
        self.deleted_handles.extend(receipt_handles)

    async def change_message_visibility(
        self,
        queue_url: str,
        receipt_handle: str,
        visibility_timeout: int = 0,
    ) -> None:
        self.visibility_changes.append((receipt_handle, visibility_timeout))

    async def send_message(
        self,
        queue_url: str,
        message_body: str,
        message_attributes: Any = None,
    ) -> str:
        self.dlq_messages.append(
            {
                "queue_url": queue_url,
                "body": message_body,
                "attributes": message_attributes,
            }
        )
        return f"dlq-msg-{len(self.dlq_messages)}"

    async def close(self) -> None:
        self.closed = True


class _MockSession:
    def __init__(self, fail_commit: bool = False) -> None:
        self.fail_commit = fail_commit
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        if self.fail_commit:
            raise OperationalError("Connection lost", {}, Exception())
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class _MockRepository:
    def __init__(self, session: _MockSession, duplicate_rate: float = 0.0) -> None:
        self.session = session
        self.duplicate_rate = duplicate_rate
        self.inserted_batches: list[list[TelemetryRecordInput]] = []

    async def insert_batch(self, records: Sequence[TelemetryRecordInput], **kwargs: Any) -> int:
        self.inserted_batches.append(list(records))
        # Simula cálculo de novos registros inseridos vs duplicados ignorados
        new_records = int(len(records) * (1.0 - self.duplicate_rate))
        return new_records


def _make_sqs_message(
    body_dict: dict[str, Any] | str,
    msg_id: str,
    receive_count: int = 1,
) -> dict[str, Any]:
    body_str = json.dumps(body_dict) if isinstance(body_dict, dict) else body_dict
    return {
        "MessageId": msg_id,
        "ReceiptHandle": f"rh-{msg_id}",
        "Body": body_str,
        "Attributes": {"ApproximateReceiveCount": str(receive_count)},
    }


def _make_valid_payload(boat_id: str = "ferry-ivete-sangalo") -> dict[str, Any]:
    return {
        "packet_id": str(uuid4()),
        "boat_id": boat_id,
        "sequence_number": 1,
        "timestamp": "2026-11-14T12:00:00+00:00",
        "navegacao": {
            "latitude": -12.97,
            "longitude": -38.50,
            "velocidade_nos": 14.0,
            "rumo_graus": 180.0,
        },
    }


@pytest.fixture
def base_settings() -> WorkerSettings:
    return WorkerSettings(
        sqs_queue_url="http://localhost:4566/000000000000/ferry-db-writer-queue",
        sqs_dlq_url="http://localhost:4566/000000000000/ferry-db-writer-queue-dlq",
        batch_size=50,
        batch_timeout_seconds=0.3,  # Rápido para testes unitários
        wait_time_seconds=0,
        max_retries=3,
    )


async def test_worker_flushes_at_exact_batch_size_50(base_settings: WorkerSettings) -> None:
    # Cria 5 lotes de 10 mensagens cada = 50 mensagens
    batches: list[list[dict[str, Any]]] = []
    for batch_idx in range(5):
        chunk = [
            _make_sqs_message(_make_valid_payload(), f"msg-{batch_idx}-{i}")
            for i in range(10)
        ]
        batches.append(chunk)

    sqs_mock = _MockSqsClient(batches)
    mock_session = _MockSession()

    @asynccontextmanager
    async def mock_session_factory():
        yield mock_session

    repo = _MockRepository(mock_session)

    worker = TelemetryBatchWorker(
        settings=base_settings,
        session_factory=mock_session_factory,  # type: ignore[arg-type]
        sqs_client=sqs_mock,
        repository_factory=lambda _: repo,
    )

    inserted = await worker.process_one_batch()

    assert inserted == 50
    assert len(repo.inserted_batches) == 1
    assert len(repo.inserted_batches[0]) == 50
    assert mock_session.committed is True
    # Todas as 50 mensagens devem ter sido excluídas do SQS
    assert len(sqs_mock.deleted_handles) == 50
    assert worker.metrics.records_inserted == 50
    assert worker.metrics.batches_flushed == 1


async def test_worker_flushes_on_time_window_when_batch_size_not_reached(
    base_settings: WorkerSettings,
) -> None:
    # Apenas 5 mensagens prontas (menos que 50)
    chunk = [_make_sqs_message(_make_valid_payload(), f"msg-{i}") for i in range(5)]
    sqs_mock = _MockSqsClient([chunk])
    mock_session = _MockSession()

    @asynccontextmanager
    async def mock_session_factory():
        yield mock_session

    repo = _MockRepository(mock_session)

    worker = TelemetryBatchWorker(
        settings=base_settings,
        session_factory=mock_session_factory,  # type: ignore[arg-type]
        sqs_client=sqs_mock,
        repository_factory=lambda _: repo,
    )

    inserted = await worker.process_one_batch()

    assert inserted == 5
    assert len(repo.inserted_batches[0]) == 5
    assert mock_session.committed is True
    assert len(sqs_mock.deleted_handles) == 5


async def test_worker_idempotency_ignores_duplicates_without_error(
    base_settings: WorkerSettings,
) -> None:
    # 10 mensagens onde 40% são duplicatas (ON CONFLICT DO NOTHING)
    chunk = [_make_sqs_message(_make_valid_payload(), f"msg-{i}") for i in range(10)]
    sqs_mock = _MockSqsClient([chunk])
    mock_session = _MockSession()

    @asynccontextmanager
    async def mock_session_factory():
        yield mock_session

    # duplicate_rate=0.4 significa 6 inseridos e 4 duplicados
    repo = _MockRepository(mock_session, duplicate_rate=0.4)

    worker = TelemetryBatchWorker(
        settings=base_settings,
        session_factory=mock_session_factory,  # type: ignore[arg-type]
        sqs_client=sqs_mock,
        repository_factory=lambda _: repo,
    )

    inserted = await worker.process_one_batch()

    assert inserted == 6
    assert worker.metrics.records_inserted == 6
    assert worker.metrics.duplicates_ignored == 4
    # Mesmo com duplicatas, commit ocorre e todas as 10 mensagens são deletadas do SQS
    assert mock_session.committed is True
    assert len(sqs_mock.deleted_handles) == 10


async def test_worker_does_not_delete_sqs_messages_when_commit_fails(
    base_settings: WorkerSettings,
) -> None:
    chunk = [_make_sqs_message(_make_valid_payload(), f"msg-{i}") for i in range(5)]
    sqs_mock = _MockSqsClient([chunk])
    mock_session = _MockSession(fail_commit=True)

    @asynccontextmanager
    async def mock_session_factory():
        yield mock_session

    repo = _MockRepository(mock_session)

    worker = TelemetryBatchWorker(
        settings=base_settings,
        session_factory=mock_session_factory,  # type: ignore[arg-type]
        sqs_client=sqs_mock,
        repository_factory=lambda _: repo,
    )

    with pytest.raises(OperationalError):
        await worker.process_one_batch()

    # Rollback foi chamado
    assert mock_session.rolled_back is True
    assert mock_session.committed is False
    # CRÍTICO: nenhuma mensagem do SQS pode ter sido excluída!
    assert len(sqs_mock.deleted_handles) == 0
    assert worker.metrics.db_failures == 1


async def test_worker_corrupted_message_retries_visibility_when_under_max_retries(
    base_settings: WorkerSettings,
) -> None:
    # Mensagem com JSON corrompido, tentativa 1 de 3
    corrupt_msg = _make_sqs_message("{corrupt json", "corrupt-1", receive_count=1)
    sqs_mock = _MockSqsClient([[corrupt_msg]])
    mock_session = _MockSession()

    @asynccontextmanager
    async def mock_session_factory():
        yield mock_session

    repo = _MockRepository(mock_session)

    worker = TelemetryBatchWorker(
        settings=base_settings,
        session_factory=mock_session_factory,  # type: ignore[arg-type]
        sqs_client=sqs_mock,
        repository_factory=lambda _: repo,
    )

    inserted = await worker.process_one_batch()

    assert inserted == 0
    assert len(repo.inserted_batches) == 0
    # Como receive_count (1) < max_retries (3), altera visibilidade para 0
    assert len(sqs_mock.visibility_changes) == 1
    assert sqs_mock.visibility_changes[0] == ("rh-corrupt-1", 0)
    # Não enviou para DLQ ainda
    assert len(sqs_mock.dlq_messages) == 0
    assert len(sqs_mock.deleted_handles) == 0
    assert worker.metrics.corrupted_messages == 1


async def test_worker_corrupted_message_forwards_to_dlq_when_retries_exhausted(
    base_settings: WorkerSettings,
) -> None:
    # Mensagem com UUID inválido, tentativa 3 de 3 (esgotou retries)
    corrupt_payload = {"packet_id": "not-a-uuid", "boat_id": "ferry-1"}
    corrupt_msg = _make_sqs_message(corrupt_payload, "corrupt-2", receive_count=3)
    sqs_mock = _MockSqsClient([[corrupt_msg]])
    mock_session = _MockSession()

    @asynccontextmanager
    async def mock_session_factory():
        yield mock_session

    repo = _MockRepository(mock_session)

    worker = TelemetryBatchWorker(
        settings=base_settings,
        session_factory=mock_session_factory,  # type: ignore[arg-type]
        sqs_client=sqs_mock,
        repository_factory=lambda _: repo,
    )

    inserted = await worker.process_one_batch()

    assert inserted == 0
    # Esgotou retries: enviou para DLQ!
    assert len(sqs_mock.dlq_messages) == 1
    dlq_item = sqs_mock.dlq_messages[0]
    assert dlq_item["queue_url"] == base_settings.sqs_dlq_url
    assert dlq_item["attributes"]["x-receive-count"]["StringValue"] == "3"
    assert "x-error-reason" in dlq_item["attributes"]
    # Deletou da fila primária após envio para DLQ
    assert sqs_mock.deleted_handles == ["rh-corrupt-2"]
    assert worker.metrics.dlq_forwarded == 1


async def test_worker_mixed_batch_processes_valid_and_routes_corrupt(
    base_settings: WorkerSettings,
) -> None:
    # Lote misto: 2 mensagens válidas e 1 corrompida esgotada
    msg_valid_1 = _make_sqs_message(_make_valid_payload(), "valid-1")
    msg_corrupt = _make_sqs_message("{bad json", "corrupt-3", receive_count=3)
    msg_valid_2 = _make_sqs_message(_make_valid_payload(), "valid-2")

    sqs_mock = _MockSqsClient([[msg_valid_1, msg_corrupt, msg_valid_2]])
    mock_session = _MockSession()

    @asynccontextmanager
    async def mock_session_factory():
        yield mock_session

    repo = _MockRepository(mock_session)

    worker = TelemetryBatchWorker(
        settings=base_settings,
        session_factory=mock_session_factory,  # type: ignore[arg-type]
        sqs_client=sqs_mock,
        repository_factory=lambda _: repo,
    )

    inserted = await worker.process_one_batch()

    assert inserted == 2
    assert len(repo.inserted_batches[0]) == 2
    assert len(sqs_mock.dlq_messages) == 1
    # As válidas foram deletadas após commit, e a corrompida foi deletada após envio à DLQ
    assert set(sqs_mock.deleted_handles) == {"rh-valid-1", "rh-valid-2", "rh-corrupt-3"}
