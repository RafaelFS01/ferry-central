"""Testes unitários e comportamentais complementares de resiliência do pipeline de ingestão (SCRUM-25)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from src.proto import telemetry_pb2
from src.server import main as server_main
from src.server.config import ServerSettings
from src.server.idempotency import (
    InMemoryIdempotencyCache,
    InvalidPacketIdError,
    validate_packet_uuid,
)
from src.server.service import TelemetryServiceServicer
from src.server.sns_publisher import SnsPublishError, SnsTelemetryPublisher
from src.worker import main as worker_main
from src.worker.config import WorkerSettings, _parse_bool as worker_parse_bool
from src.worker.consumer import TelemetryBatchWorker
from src.worker.sqs_client import BotoSqsClient


# ---------------------------------------------------------------------------
# 1. ServerSettings & InMemoryIdempotencyCache edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("env_var", "value", "match_pattern"),
    [
        ("IDEMPOTENCY_CACHE_SIZE", "-1", "IDEMPOTENCY_CACHE_SIZE"),
        ("IDEMPOTENCY_CACHE_TTL_SECONDS", "-5", "IDEMPOTENCY_CACHE_TTL_SECONDS"),
        ("GRPC_SHUTDOWN_GRACE_SECONDS", "-1", "GRPC_SHUTDOWN_GRACE_SECONDS"),
        ("GRPC_MAX_MESSAGE_LENGTH_BYTES", "0", "GRPC_MAX_MESSAGE_LENGTH_BYTES"),
    ],
)
def test_server_settings_rejects_negative_or_zero_limits(
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
    value: str,
    match_pattern: str,
) -> None:
    monkeypatch.setenv("INGESTION_MODE", "direct")
    monkeypatch.setenv(env_var, value)
    with pytest.raises(ValueError, match=match_pattern):
        ServerSettings.from_env()


def test_server_settings_bind_address_and_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "sa-east-1")
    monkeypatch.delenv("REST_PORT", raising=False)
    monkeypatch.delenv("REST_HOST", raising=False)
    monkeypatch.setenv("API_PORT", "8090")
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("GRPC_HOST", "127.0.0.1")
    monkeypatch.setenv("GRPC_PORT", "50055")

    cfg = ServerSettings.from_env()
    assert cfg.bind_address == "127.0.0.1:50055"
    assert cfg.aws_region == "sa-east-1"
    assert cfg.rest_port == 8090
    assert cfg.rest_host == "127.0.0.1"


def test_idempotency_cache_disabled_purge_and_validation_edges() -> None:
    with pytest.raises(ValueError, match="max_size"):
        InMemoryIdempotencyCache(max_size=-1)
    with pytest.raises(ValueError, match="ttl_seconds"):
        InMemoryIdempotencyCache(ttl_seconds=-1.0)
    with pytest.raises(InvalidPacketIdError):
        validate_packet_uuid(None)  # type: ignore[arg-type]

    # Cache desabilitado (max_size=0 ou ttl_seconds=0)
    uid = uuid4()
    zero_size = InMemoryIdempotencyCache(max_size=0, ttl_seconds=60.0)
    zero_size.mark_processed(uid)
    assert zero_size.contains(uid) is False
    assert len(zero_size) == 0

    zero_ttl = InMemoryIdempotencyCache(max_size=10, ttl_seconds=0.0)
    zero_ttl.mark_processed(uid)
    assert zero_ttl.contains(uid) is False

    # _purge_expired_head limpa entradas antigas ao inserir novas
    now = 10.0
    cache = InMemoryIdempotencyCache(max_size=10, ttl_seconds=5.0, clock=lambda: now)
    p1, p2 = uuid4(), uuid4()
    cache.mark_processed(p1)
    assert len(cache) == 1
    now += 6.0
    cache.mark_processed(p2)
    assert len(cache) == 1
    assert cache.contains(p1) is False
    assert cache.contains(p2) is True


# ---------------------------------------------------------------------------
# 2. TelemetryServiceServicer constructor & cancellation / rollback resilience
# ---------------------------------------------------------------------------


def test_servicer_constructor_validates_required_dependencies() -> None:
    with pytest.raises(ValueError, match="Pelo menos um caminho"):
        TelemetryServiceServicer(
            ServerSettings(direct_path_enabled=False, decoupled_path_enabled=False)
        )

    with pytest.raises(ValueError, match="session_factory"):
        TelemetryServiceServicer(
            ServerSettings(direct_path_enabled=True, decoupled_path_enabled=False),
            session_factory=None,
        )

    with pytest.raises(ValueError, match="publisher"):
        TelemetryServiceServicer(
            ServerSettings(direct_path_enabled=False, decoupled_path_enabled=True),
            publisher=None,
        )


async def test_servicer_propagates_cancelled_error_and_handles_rollback_failure() -> None:
    class _BrokenRollbackSession:
        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            raise RuntimeError("falha secundaria no rollback")

    @asynccontextmanager
    async def _broken_session_factory():
        yield _BrokenRollbackSession()

    class _CancellingRepo:
        async def exists_packet(self, _pid) -> bool:
            return False

        async def insert_packet(self, _rec) -> bool:
            raise asyncio.CancelledError()

    class _OkPublisher:
        async def publish(self, payload, message_attributes=None) -> str:
            return "msg-1"

        async def close(self) -> None:
            return None

    class _DummyContext:
        def invocation_metadata(self):
            return ()

        async def abort(self, code, details):
            raise AssertionError(f"Não deveria abortar em CancelledError: {code} {details}")

    settings = ServerSettings(direct_path_enabled=True, decoupled_path_enabled=True)
    servicer = TelemetryServiceServicer(
        settings=settings,
        session_factory=_broken_session_factory,  # type: ignore[arg-type]
        publisher=_OkPublisher(),
        repository_factory=lambda _: _CancellingRepo(),  # type: ignore[arg-type]
    )

    packet = telemetry_pb2.TelemetryPacket(
        message_id=str(uuid4()),
        boat_id="ferry-cancel",
        timestamp_coleta=1762800000000,
        passageiros=10,
        navegacao=telemetry_pb2.NavigationData(
            latitude=-12.97,
            longitude=-38.50,
            velocidade_nos=10.0,
            rumo_graus=180.0,
            status_navegacao=telemetry_pb2.NAVIGATION_STATUS_EM_TRAVESSIA,
        ),
    )

    with pytest.raises(asyncio.CancelledError):
        await servicer.EnviarTelemetria(packet, _DummyContext())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. SnsTelemetryPublisher edge cases (lock, errors, close, attributes)
# ---------------------------------------------------------------------------


async def test_sns_publisher_validation_concurrency_errors_and_close() -> None:
    with pytest.raises(ValueError, match="sns_topic_arn"):
        SnsTelemetryPublisher(topic_arn=None, topic_name="")

    class _FakeSnsClient:
        def __init__(self, *, missing_arn: bool = False, fail_create: bool = False) -> None:
            self.missing_arn = missing_arn
            self.fail_create = fail_create
            self.create_calls = 0
            self.published: list[dict[str, Any]] = []
            self.closed = False

        def create_topic(self, Name: str) -> dict[str, str]:
            self.create_calls += 1
            if self.fail_create:
                raise ClientError(
                    {"Error": {"Code": "AccessDenied", "Message": "Denied"}},
                    "CreateTopic",
                )
            if self.missing_arn:
                return {}
            return {"TopicArn": f"arn:aws:sns:us-east-1:000000000000:{Name}"}

        def publish(self, **kwargs: Any) -> dict[str, str]:
            self.published.append(kwargs)
            return {"MessageId": f"id-{len(self.published)}"}

        def close(self) -> None:
            self.closed = True

    # Resolução concorrente só chama create_topic uma única vez
    client_ok = _FakeSnsClient()
    pub = SnsTelemetryPublisher(topic_name="ferry-topic", boto_client=client_ok)
    ids = await asyncio.gather(
        pub.publish({"a": 1}, message_attributes={"k": "v", "empty": ""}),
        pub.publish({"a": 2}, message_attributes={"empty": ""}),
    )
    assert len(ids) == 2
    assert client_ok.create_calls == 1
    assert "MessageAttributes" in client_ok.published[0] or "MessageAttributes" in client_ok.published[1]
    assert any("MessageAttributes" not in call for call in client_ok.published)

    # Cliente injetado externamente não é fechado por close()
    await pub.close()
    assert client_ok.closed is False

    # Cliente pertencente ao publisher é fechado por close()
    pub._owns_client = True
    await pub.close()
    assert client_ok.closed is True

    # TopicArn ausente na resposta -> SnsPublishError
    pub_missing = SnsTelemetryPublisher(
        topic_name="ferry-topic",
        boto_client=_FakeSnsClient(missing_arn=True),
    )
    with pytest.raises(SnsPublishError, match="TopicArn"):
        await pub_missing.publish({"a": 1})

    # Erro ClientError ao criar/resolver tópico -> SnsPublishError
    pub_denied = SnsTelemetryPublisher(
        topic_name="ferry-topic",
        boto_client=_FakeSnsClient(fail_create=True),
    )
    with pytest.raises(SnsPublishError, match="Falha ao resolver ARN"):
        await pub_denied.publish({"a": 1})


# ---------------------------------------------------------------------------
# 4. src/server/main.py lifecycle (bind failure, shutdown, serve)
# ---------------------------------------------------------------------------


async def test_server_main_bind_failure_closes_owned_publisher_and_shutdown_disposes_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_main.configure_logging("WARNING")

    closed_owned = False

    class _OwnedFakePublisher:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def publish(self, payload, message_attributes=None) -> str:
            return "m1"

        async def close(self) -> None:
            nonlocal closed_owned
            closed_owned = True

    class _FailBindServer:
        def add_insecure_port(self, _addr: str) -> int:
            return 0

        def add_generic_rpc_handlers(self, _handlers: Any) -> None:
            return None

        def add_registered_method_handlers(self, _name: str, _handlers: Any) -> None:
            return None

    monkeypatch.setattr(server_main, "SnsTelemetryPublisher", _OwnedFakePublisher)
    monkeypatch.setattr(server_main.grpc.aio, "server", lambda options=None: _FailBindServer())

    settings = ServerSettings(
        grpc_host="127.0.0.1",
        grpc_port=50099,
        direct_path_enabled=False,
        decoupled_path_enabled=True,
    )
    with pytest.raises(RuntimeError, match="Não foi possível fazer bind"):
        await server_main.build_server(settings)
    assert closed_owned is True


async def test_server_main_serve_lifecycle_graceful_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disposed = False
    stopped = False
    started = False
    pub_closed = False

    class _FakeHealthServicer:
        async def set(self, _service: str, _status: Any) -> None:
            return None

    class _FakeGrpcServer:
        async def start(self) -> None:
            nonlocal started
            started = True

        async def wait_for_termination(self) -> None:
            await asyncio.sleep(0.01)

        async def stop(self, grace: float | None = None) -> None:
            nonlocal stopped
            stopped = True

    class _FakePub:
        async def close(self) -> None:
            nonlocal pub_closed
            pub_closed = True

    cfg = ServerSettings(
        grpc_host="127.0.0.1",
        grpc_port=0,
        direct_path_enabled=True,
        decoupled_path_enabled=False,
        shutdown_grace_seconds=0.1,
    )
    runtime = server_main.GrpcServerRuntime(
        server=_FakeGrpcServer(),  # type: ignore[arg-type]
        health_servicer=_FakeHealthServicer(),  # type: ignore[arg-type]
        publisher=_FakePub(),  # type: ignore[arg-type]
        settings=cfg,
        bound_port=50051,
    )

    async def _fake_build(_cfg: ServerSettings) -> server_main.GrpcServerRuntime:
        return runtime

    async def _fake_dispose() -> None:
        nonlocal disposed
        disposed = True

    monkeypatch.setattr(server_main, "build_server", _fake_build)
    monkeypatch.setattr(server_main, "dispose_engine", _fake_dispose)

    await server_main.serve(cfg)

    assert started is True
    assert stopped is True
    assert pub_closed is True
    assert disposed is True


# ---------------------------------------------------------------------------
# 5. Worker config, SQS client, consumer & main resilience paths
# ---------------------------------------------------------------------------


def test_worker_config_additional_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    assert worker_parse_bool(None, True) is True
    assert worker_parse_bool("yes", False) is True
    assert worker_parse_bool("false", True) is False

    monkeypatch.setenv("WORKER_SHUTDOWN_GRACE_SECONDS", "-2.0")
    with pytest.raises(ValueError, match="WORKER_SHUTDOWN_GRACE_SECONDS"):
        WorkerSettings.from_env()


async def test_sqs_client_empty_delete_partial_failure_visibility_error_and_close() -> None:
    class _PartialFailBotoSqs:
        def __init__(self) -> None:
            self.deleted_entries: list[list[dict[str, str]]] = []
            self.closed = False

        def delete_message_batch(self, QueueUrl: str, Entries: list[dict[str, str]]) -> dict[str, Any]:
            self.deleted_entries.append(Entries)
            return {"Failed": [{"Id": "0", "Code": "ReceiptHandleIsInvalid"}]}

        def change_message_visibility(self, **kwargs: Any) -> None:
            raise ClientError({"Error": {"Code": "500", "Message": "err"}}, "ChangeVis")

        def close(self) -> None:
            self.closed = True

    fake_boto = _PartialFailBotoSqs()
    client = BotoSqsClient(boto_client=fake_boto)

    # Lista vazia não chama API
    await client.delete_messages_batch("http://localhost:4566/q", [])
    assert fake_boto.deleted_entries == []

    # Handles duplicados são deduplicados antes da chamada e falhas parciais são logadas
    await client.delete_messages_batch("http://localhost:4566/q", ["rh-1", "rh-1", "rh-2"])
    assert len(fake_boto.deleted_entries) == 1
    assert len(fake_boto.deleted_entries[0]) == 2

    with pytest.raises(ClientError):
        await client.change_message_visibility("http://localhost:4566/q", "rh-1", 0)

    await client.close()
    assert fake_boto.closed is False
    client._owns_client = True
    await client.close()
    assert fake_boto.closed is True


async def test_worker_consumer_resilience_dlq_visibility_delete_failure_and_run_loop() -> None:
    class _FaultySqs:
        def __init__(self, batches: list[list[dict[str, Any]]]) -> None:
            self.batches = list(batches)
            self.fail_send = False
            self.fail_visibility = False
            self.fail_delete = False
            self.closed = False

        async def receive_messages(
            self, queue_url: str, max_number: int = 10, wait_time_seconds: int = 20
        ) -> list[dict[str, Any]]:
            if self.batches:
                return self.batches.pop(0)
            return []

        async def delete_messages_batch(
            self, queue_url: str, receipt_handles: Sequence[str]
        ) -> None:
            if self.fail_delete:
                raise RuntimeError("SQS delete timeout")

        async def change_message_visibility(
            self, queue_url: str, receipt_handle: str, visibility_timeout: int = 0
        ) -> None:
            if self.fail_visibility:
                raise RuntimeError("SQS visibility error")

        async def send_message(
            self, queue_url: str, message_body: str, message_attributes: Any = None
        ) -> str:
            if self.fail_send:
                raise RuntimeError("DLQ unreachable")
            return "dlq-1"

        async def close(self) -> None:
            self.closed = True

    class _SimpleSession:
        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    @asynccontextmanager
    async def _session_factory():
        yield _SimpleSession()

    class _Repo:
        async def insert_batch(self, records: Sequence[Any], **kwargs: Any) -> int:
            return len(records)

    valid_body = json.dumps(
        {
            "packet_id": str(uuid4()),
            "boat_id": "ferry-worker",
            "sequence_number": 1,
            "timestamp": "2026-11-18T12:00:00Z",
            "latitude": -12.97,
            "longitude": -38.50,
        }
    )

    # 1) Mensagem corrompida sem DLQ configurada + falha em visibility + delete após commit
    corrupt_no_dlq = {
        "MessageId": "m-corrupt-nodlq",
        "ReceiptHandle": "rh-nodlq",
        "Body": "{bad",
        "Attributes": {"ApproximateReceiveCount": "3"},
    }
    sqs_no_dlq = _FaultySqs([[corrupt_no_dlq]])
    settings_no_dlq = WorkerSettings(
        sqs_dlq_url=None,
        batch_size=5,
        batch_timeout_seconds=0.05,
        wait_time_seconds=0,
        max_retries=3,
    )
    worker_no_dlq = TelemetryBatchWorker(
        settings=settings_no_dlq,
        session_factory=_session_factory,  # type: ignore[arg-type]
        sqs_client=sqs_no_dlq,
        repository_factory=lambda _: _Repo(),  # type: ignore[arg-type]
    )
    assert worker_no_dlq.is_running is True
    assert await worker_no_dlq.process_one_batch() == 0
    assert worker_no_dlq.metrics.corrupted_messages == 1
    assert worker_no_dlq.metrics.dlq_forwarded == 0

    # 2) Falha ao enviar para DLQ e falha ao ajustar visibilidade não derrubam o worker
    corrupt_retry = {
        "MessageId": "m-corrupt-retry",
        "ReceiptHandle": "rh-retry",
        "Body": "{bad",
        "Attributes": {"ApproximateReceiveCount": "1"},
    }
    corrupt_dlq = {
        "MessageId": "m-corrupt-dlq",
        "ReceiptHandle": "rh-dlq",
        "Body": "{bad",
        "Attributes": {"ApproximateReceiveCount": "3"},
    }
    valid_msg = {
        "MessageId": "m-valid",
        "ReceiptHandle": "rh-valid",
        "Body": valid_body,
        "Attributes": {"ApproximateReceiveCount": "1"},
    }
    sqs_faulty = _FaultySqs([[corrupt_retry, corrupt_dlq, valid_msg]])
    sqs_faulty.fail_send = True
    sqs_faulty.fail_visibility = True
    sqs_faulty.fail_delete = True

    settings_with_dlq = WorkerSettings(
        sqs_dlq_url="http://localhost:4566/000000000000/dlq",
        batch_size=5,
        batch_timeout_seconds=0.05,
        wait_time_seconds=0,
        max_retries=3,
    )
    worker = TelemetryBatchWorker(
        settings=settings_with_dlq,
        session_factory=_session_factory,  # type: ignore[arg-type]
        sqs_client=sqs_faulty,
        repository_factory=lambda _: _Repo(),  # type: ignore[arg-type]
    )
    # Mesmo com erro no delete pós-commit, registro foi gravado e contado
    assert await worker.process_one_batch() == 1
    assert worker.metrics.records_inserted == 1

    # Fila vazia retorna 0 imediatamente
    assert await worker.process_one_batch() == 0

    # Loop run() interrompe cooperativamente via stop()
    worker.stop()
    assert worker.is_running is False
    await worker.run()
    await worker.close()


async def test_worker_main_run_worker_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    worker_main.configure_logging("INFO")
    engine_disposed = False
    sqs_closed = False

    class _FakeEngine:
        async def dispose(self) -> None:
            nonlocal engine_disposed
            engine_disposed = True

    class _FakeSqs:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def close(self) -> None:
            nonlocal sqs_closed
            sqs_closed = True

    class _FakeWorker:
        def __init__(self, **_kwargs: Any) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

        async def run(self) -> None:
            await asyncio.sleep(0)

        async def close(self) -> None:
            self.stopped = True

    monkeypatch.setattr(worker_main, "create_async_db_engine", lambda _cfg: _FakeEngine())
    monkeypatch.setattr(worker_main, "create_session_factory", lambda _eng: object())
    monkeypatch.setattr(worker_main, "BotoSqsClient", _FakeSqs)
    monkeypatch.setattr(worker_main, "TelemetryBatchWorker", _FakeWorker)

    await worker_main.run_worker(WorkerSettings())
    assert engine_disposed is True
    assert sqs_closed is True
