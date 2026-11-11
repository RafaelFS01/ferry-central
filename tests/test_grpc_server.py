"""Testes ponta-a-ponta gRPC assíncronos (grpc.aio) do servidor da Central."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import grpc
import pytest
from grpc_health.v1 import health_pb2, health_pb2_grpc
from sqlalchemy.exc import OperationalError

from src.database.repository import TelemetryRecordInput
from src.proto import telemetry_pb2, telemetry_pb2_grpc
from src.server.config import ServerSettings
from src.server.idempotency import IdempotencyGuard, InMemoryIdempotencyCache
from src.server.main import TELEMETRY_SERVICE_NAME, build_server, shutdown_runtime
from src.server.sns_publisher import SnsPublishError


class _FakeSession:
    def __init__(self, store: dict[UUID, TelemetryRecordInput]) -> None:
        self._store = store
        self._pending: dict[UUID, TelemetryRecordInput] = {}
        self.commits = 0
        self.rollbacks = 0

    def stage(self, record: TelemetryRecordInput) -> bool:
        if record.packet_id in self._store or record.packet_id in self._pending:
            return False
        self._pending[record.packet_id] = record
        return True

    def has_packet(self, packet_id: UUID) -> bool:
        return packet_id in self._store or packet_id in self._pending

    async def commit(self) -> None:
        self.commits += 1
        self._store.update(self._pending)
        self._pending.clear()

    async def rollback(self) -> None:
        self.rollbacks += 1
        self._pending.clear()


class _FakeSessionFactory:
    def __init__(self, store: dict[UUID, TelemetryRecordInput] | None = None) -> None:
        self._store = store if store is not None else {}
        self.sessions: list[_FakeSession] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[_FakeSession]:
        session = _FakeSession(self._store)
        self.sessions.append(session)
        yield session


class _FakeTelemetryRepository:
    def __init__(
        self,
        store: dict[UUID, TelemetryRecordInput],
        session: _FakeSession | None = None,
        *,
        on_insert: Any | None = None,
        fail_with: BaseException | None = None,
    ) -> None:
        self._store = store
        self._session = session
        self._on_insert = on_insert
        self._fail_with = fail_with
        self.exists_calls: list[UUID] = []
        self.insert_calls: list[UUID] = []

    async def exists_packet(self, packet_id: UUID) -> bool:
        self.exists_calls.append(packet_id)
        if self._fail_with is not None:
            raise self._fail_with
        if self._session is not None:
            return self._session.has_packet(packet_id)
        return packet_id in self._store

    async def insert_packet(self, record: TelemetryRecordInput) -> bool:
        self.insert_calls.append(record.packet_id)
        if self._on_insert is not None:
            await self._on_insert(record)
        if self._fail_with is not None:
            raise self._fail_with
        if self._session is not None:
            return self._session.stage(record)
        if record.packet_id in self._store:
            return False
        self._store[record.packet_id] = record
        return True


class _FakePublisher:
    def __init__(
        self,
        *,
        on_publish: Any | None = None,
        fail_with: BaseException | None = None,
    ) -> None:
        self.messages: list[tuple[dict[str, Any], dict[str, str]]] = []
        self.closed = False
        self._on_publish = on_publish
        self._fail_with = fail_with

    async def publish(
        self,
        payload: Mapping[str, Any],
        message_attributes: Mapping[str, str] | None = None,
    ) -> str:
        if self._on_publish is not None:
            await self._on_publish(payload)
        if self._fail_with is not None:
            raise self._fail_with
        self.messages.append((dict(payload), dict(message_attributes or {})))
        return f"msg-{len(self.messages)}"

    async def close(self) -> None:
        self.closed = True


def _sample_packet(message_id: str | None = None) -> telemetry_pb2.TelemetryPacket:
    return telemetry_pb2.TelemetryPacket(
        message_id=message_id or str(uuid4()),
        boat_id="ferry-ivete-sangalo",
        timestamp_coleta=1762800000000,
        passageiros=280,
        navegacao=telemetry_pb2.NavigationData(
            latitude=-12.9714,
            longitude=-38.5014,
            velocidade_nos=14.0,
            rumo_graus=240.0,
            status_navegacao=telemetry_pb2.NAVIGATION_STATUS_EM_TRAVESSIA,
        ),
        propulsao=telemetry_pb2.PropulsionData(
            rpm_motor=1400.0,
            temperatura_motor_celsius=80.0,
            pressao_oleo_bar=4.1,
            nivel_combustivel_percentual=82.5,
            consumo_instantaneo_lph=110.0,
        ),
        rede=telemetry_pb2.NetworkDiagnostics(
            rssi_dbm=-70,
            latencia_rtt_ms=28.0,
            perda_pacotes_percentual=0.0,
            tamanho_buffer_local=0,
            tentativa_envio=1,
            tipo_enlace=telemetry_pb2.LINK_TYPE_4G_5G_COSTEIRO,
        ),
    )


async def test_grpc_server_concurrent_direct_and_decoupled_paths() -> None:
    store: dict[UUID, TelemetryRecordInput] = {}
    barrier = asyncio.Barrier(2)
    repos: list[_FakeTelemetryRepository] = []

    async def wait_barrier(_: Any) -> None:
        await barrier.wait()

    def repo_factory(session: Any) -> _FakeTelemetryRepository:
        repo = _FakeTelemetryRepository(store, session=session, on_insert=wait_barrier)
        repos.append(repo)
        return repo

    publisher = _FakePublisher(on_publish=wait_barrier)
    session_factory = _FakeSessionFactory(store)
    settings = ServerSettings(
        grpc_host="127.0.0.1",
        grpc_port=0,
        direct_path_enabled=True,
        decoupled_path_enabled=True,
        sns_topic_name="ferry-telemetry-topic",
    )

    from src.server.service import TelemetryServiceServicer

    servicer = TelemetryServiceServicer(
        settings=settings,
        session_factory=session_factory,  # type: ignore[arg-type]
        publisher=publisher,
        repository_factory=repo_factory,  # type: ignore[arg-type]
    )
    server = grpc.aio.server()
    telemetry_pb2_grpc.add_TelemetryServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()

    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = telemetry_pb2_grpc.TelemetryServiceStub(channel)
            packet = _sample_packet()
            ack = await stub.EnviarTelemetria(packet)

        assert ack.message_id == packet.message_id
        assert ack.sucesso is True
        assert ack.duplicado is False
        assert ack.status == telemetry_pb2.ACK_STATUS_ACEITO
        assert ack.processado_em > 0

        pid = UUID(packet.message_id)
        assert pid in store
        assert len(publisher.messages) == 1
        assert publisher.messages[0][0]["packet_id"] == packet.message_id
        assert any(r.exists_calls == [pid] for r in repos)
    finally:
        await server.stop(grace=1.0)


async def test_grpc_server_deduplication_cache_and_pre_persistence_db_check() -> None:
    existing_id = uuid4()
    store: dict[UUID, TelemetryRecordInput] = {
        existing_id: TelemetryRecordInput(
            packet_id=existing_id,
            boat_id="ferry-ivete-sangalo",
            sequence_number=1,
            timestamp=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            latitude=-12.97,
            longitude=-38.50,
        )
    }
    insert_calls: list[UUID] = []

    class _TrackingRepo(_FakeTelemetryRepository):
        async def insert_packet(self, record: TelemetryRecordInput) -> bool:
            insert_calls.append(record.packet_id)
            return await super().insert_packet(record)

    publisher = _FakePublisher()
    session_factory = _FakeSessionFactory(store)
    settings = ServerSettings(
        grpc_host="127.0.0.1",
        grpc_port=0,
        direct_path_enabled=True,
        decoupled_path_enabled=True,
    )

    from src.server.service import TelemetryServiceServicer

    servicer = TelemetryServiceServicer(
        settings=settings,
        session_factory=session_factory,  # type: ignore[arg-type]
        publisher=publisher,
        idempotency=IdempotencyGuard(InMemoryIdempotencyCache(max_size=100, ttl_seconds=60.0)),
        repository_factory=lambda s: _TrackingRepo(store, session=s),  # type: ignore[arg-type]
    )
    server = grpc.aio.server()
    telemetry_pb2_grpc.add_TelemetryServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()

    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = telemetry_pb2_grpc.TelemetryServiceStub(channel)

            # 1) Pacote já presente no PostgreSQL (cache frio) deve ser ignorado ANTES de persistir/publicar
            ack_db_dup = await stub.EnviarTelemetria(_sample_packet(str(existing_id)))
            assert ack_db_dup.sucesso is True
            assert ack_db_dup.duplicado is True
            assert ack_db_dup.status == telemetry_pb2.ACK_STATUS_DUPLICADO_IGNORADO
            assert insert_calls == []
            assert publisher.messages == []

            # 2) Novo pacote é aceito uma vez e reenvio imediato é ignorado via cache
            new_packet = _sample_packet()
            ack_first = await stub.EnviarTelemetria(new_packet)
            ack_second = await stub.EnviarTelemetria(new_packet)

            assert ack_first.sucesso is True
            assert ack_first.duplicado is False
            assert ack_first.status == telemetry_pb2.ACK_STATUS_ACEITO

            assert ack_second.sucesso is True
            assert ack_second.duplicado is True
            assert ack_second.status == telemetry_pb2.ACK_STATUS_DUPLICADO_IGNORADO

            assert insert_calls == [UUID(new_packet.message_id)]
            assert len(publisher.messages) == 1
    finally:
        await server.stop(grace=1.0)


async def test_grpc_server_maps_validation_db_and_sns_errors_to_status_codes() -> None:
    store: dict[UUID, TelemetryRecordInput] = {}
    session_factory = _FakeSessionFactory(store)
    settings = ServerSettings(
        grpc_host="127.0.0.1",
        grpc_port=0,
        direct_path_enabled=True,
        decoupled_path_enabled=True,
    )

    db_error: BaseException | None = None
    sns_error: BaseException | None = None

    class _DynamicRepo(_FakeTelemetryRepository):
        async def exists_packet(self, packet_id: UUID) -> bool:
            if db_error is not None:
                raise db_error
            return await super().exists_packet(packet_id)

    class _DynamicPublisher(_FakePublisher):
        async def publish(
            self,
            payload: Mapping[str, Any],
            message_attributes: Mapping[str, str] | None = None,
        ) -> str:
            if sns_error is not None:
                raise sns_error
            return await super().publish(payload, message_attributes)

    from src.server.service import TelemetryServiceServicer

    publisher = _DynamicPublisher()
    servicer = TelemetryServiceServicer(
        settings=settings,
        session_factory=session_factory,  # type: ignore[arg-type]
        publisher=publisher,
        repository_factory=lambda s: _DynamicRepo(store, session=s),  # type: ignore[arg-type]
    )
    server = grpc.aio.server()
    telemetry_pb2_grpc.add_TelemetryServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()

    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = telemetry_pb2_grpc.TelemetryServiceStub(channel)

            # 1) Erro de validação -> INVALID_ARGUMENT
            with pytest.raises(grpc.aio.AioRpcError) as exc_invalid:
                await stub.EnviarTelemetria(_sample_packet("uuid-invalido"))
            assert exc_invalid.value.code() == grpc.StatusCode.INVALID_ARGUMENT

            # 2) Falha de banco -> UNAVAILABLE (e não marca idempotência)
            retry_packet = _sample_packet()
            db_error = OperationalError("SELECT 1", {}, Exception("connection refused"))
            with pytest.raises(grpc.aio.AioRpcError) as exc_db:
                await stub.EnviarTelemetria(retry_packet)
            assert exc_db.value.code() == grpc.StatusCode.UNAVAILABLE
            db_error = None

            # 3) Falha SNS -> UNAVAILABLE (e não marca idempotência)
            sns_error = SnsPublishError("sns timeout")
            with pytest.raises(grpc.aio.AioRpcError) as exc_sns:
                await stub.EnviarTelemetria(retry_packet)
            assert exc_sns.value.code() == grpc.StatusCode.UNAVAILABLE
            sns_error = None

            # 4) Retry posterior deve ser aceito normalmente
            ack_retry = await stub.EnviarTelemetria(retry_packet)
            assert ack_retry.sucesso is True
            assert ack_retry.duplicado is False
            assert ack_retry.status == telemetry_pb2.ACK_STATUS_ACEITO

            # 5) Erro inesperado -> INTERNAL
            db_error = RuntimeError("bug inesperado")
            with pytest.raises(grpc.aio.AioRpcError) as exc_internal:
                await stub.EnviarTelemetria(_sample_packet())
            assert exc_internal.value.code() == grpc.StatusCode.INTERNAL
    finally:
        await server.stop(grace=1.0)


async def test_build_server_registers_health_and_graceful_shutdown() -> None:
    publisher = _FakePublisher()
    settings = ServerSettings(
        grpc_host="127.0.0.1",
        grpc_port=0,
        direct_path_enabled=False,
        decoupled_path_enabled=True,
        shutdown_grace_seconds=0.5,
    )
    runtime = await build_server(settings, publisher=publisher)
    await runtime.server.start()

    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{runtime.bound_port}") as channel:
            health_stub = health_pb2_grpc.HealthStub(channel)
            resp = await health_stub.Check(
                health_pb2.HealthCheckRequest(service=TELEMETRY_SERVICE_NAME)
            )
            assert resp.status == health_pb2.HealthCheckResponse.SERVING

            telemetry_stub = telemetry_pb2_grpc.TelemetryServiceStub(channel)
            ack = await telemetry_stub.EnviarTelemetria(_sample_packet())
            assert ack.sucesso is True
            assert ack.status == telemetry_pb2.ACK_STATUS_ACEITO
    finally:
        await shutdown_runtime(runtime, dispose_db=False)

    assert publisher.closed is True

