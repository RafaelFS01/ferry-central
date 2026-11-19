"""Testes de integração gRPC assíncronos com SQLite em memória, idempotência UUIDv4 e SNS/SQS (SCRUM-25)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID, uuid4

import grpc
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database.models import Telemetry
from src.database.repository import TelemetryRepository
from src.proto import telemetry_pb2, telemetry_pb2_grpc
from src.server.config import ServerSettings
from src.server.idempotency import IdempotencyGuard, InMemoryIdempotencyCache
from src.server.main import build_server, shutdown_runtime
from src.server.sns_publisher import SnsPublishError
from src.worker.config import WorkerSettings
from src.worker.consumer import TelemetryBatchWorker


class _InMemorySnsToSqsBridge:
    """Simula publicação assíncrona no SNS com fan-out em envelope padrão para uma fila SQS em memória."""

    def __init__(self, *, fail_publish: bool = False) -> None:
        self.fail_publish = fail_publish
        self.published_events: list[tuple[dict[str, Any], dict[str, str]]] = []
        self.sqs_queue: list[dict[str, Any]] = []
        self.deleted_handles: list[str] = []
        self.closed = False
        self._msg_seq = 0

    async def publish(
        self,
        payload: Mapping[str, Any],
        message_attributes: Mapping[str, str] | None = None,
    ) -> str:
        if self.fail_publish:
            raise SnsPublishError("Falha simulada ao publicar no SNS")

        self._msg_seq += 1
        msg_id = f"sns-msg-{self._msg_seq}"
        payload_copy = dict(payload)
        attrs_copy = dict(message_attributes or {})
        self.published_events.append((payload_copy, attrs_copy))

        sns_envelope = {
            "Type": "Notification",
            "MessageId": msg_id,
            "TopicArn": "arn:aws:sns:us-east-1:000000000000:ferry-telemetria-topic",
            "Message": json.dumps(payload_copy),
        }
        self.sqs_queue.append(
            {
                "MessageId": f"sqs-{self._msg_seq}",
                "ReceiptHandle": f"rh-{self._msg_seq}",
                "Body": json.dumps(sns_envelope),
                "Attributes": {"ApproximateReceiveCount": "1"},
            }
        )
        return msg_id

    async def receive_messages(
        self,
        queue_url: str,
        max_number: int = 10,
        wait_time_seconds: int = 20,
    ) -> list[dict[str, Any]]:
        if not self.sqs_queue:
            return []
        chunk = self.sqs_queue[:max_number]
        del self.sqs_queue[:max_number]
        return chunk

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
        return None

    async def send_message(
        self,
        queue_url: str,
        message_body: str,
        message_attributes: Mapping[str, Any] | None = None,
    ) -> str:
        self._msg_seq += 1
        return f"dlq-{self._msg_seq}"

    async def close(self) -> None:
        self.closed = True


def _sample_packet(
    message_id: str | None = None,
    *,
    boat_id: str = "ferry-ivete-sangalo",
    timestamp_coleta: int = 1762800000000,
    passageiros: int = 310,
) -> telemetry_pb2.TelemetryPacket:
    return telemetry_pb2.TelemetryPacket(
        message_id=message_id or str(uuid4()),
        boat_id=boat_id,
        timestamp_coleta=timestamp_coleta,
        passageiros=passageiros,
        navegacao=telemetry_pb2.NavigationData(
            latitude=-12.9714,
            longitude=-38.5014,
            velocidade_nos=14.4,
            rumo_graus=248.0,
            status_navegacao=telemetry_pb2.NAVIGATION_STATUS_EM_TRAVESSIA,
        ),
        propulsao=telemetry_pb2.PropulsionData(
            rpm_motor=1580.0,
            temperatura_motor_celsius=82.0,
            pressao_oleo_bar=4.2,
            nivel_combustivel_percentual=79.5,
            consumo_instantaneo_lph=121.0,
        ),
        rede=telemetry_pb2.NetworkDiagnostics(
            rssi_dbm=-71,
            latencia_rtt_ms=27.5,
            perda_pacotes_percentual=0.2,
            tamanho_buffer_local=0,
            tentativa_envio=1,
            tipo_enlace=telemetry_pb2.LINK_TYPE_4G_5G_COSTEIRO,
        ),
    )


async def _count_rows(
    session_factory: async_sessionmaker[AsyncSession],
    packet_id: UUID | None = None,
) -> int:
    async with session_factory() as session:
        stmt = select(func.count()).select_from(Telemetry)
        if packet_id is not None:
            stmt = stmt.where(Telemetry.packet_id == packet_id)
        return int(await session.scalar(stmt) or 0)


async def test_grpc_direct_ingestion_persists_packet_in_sqlite_database(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Valida ciclo completo gRPC -> validação Protobuf -> persistência real em SQLite."""
    settings = ServerSettings(
        grpc_host="127.0.0.1",
        grpc_port=0,
        direct_path_enabled=True,
        decoupled_path_enabled=False,
        shutdown_grace_seconds=0.5,
    )
    runtime = await build_server(settings, session_factory=sqlite_session_factory)
    await runtime.server.start()

    try:
        packet = _sample_packet()
        async with grpc.aio.insecure_channel(f"127.0.0.1:{runtime.bound_port}") as channel:
            stub = telemetry_pb2_grpc.TelemetryServiceStub(channel)
            ack = await stub.EnviarTelemetria(
                packet,
                metadata=(("x-sequence-number", "15"),),
            )

        assert ack.message_id == packet.message_id
        assert ack.sucesso is True
        assert ack.duplicado is False
        assert ack.status == telemetry_pb2.ACK_STATUS_ACEITO
        assert ack.processado_em > 0

        async with sqlite_session_factory() as session:
            repo = TelemetryRepository(session)
            saved = await repo.get_by_packet_id(UUID(packet.message_id))
            assert saved is not None
            assert saved.boat_id == "ferry-ivete-sangalo"
            assert saved.sequence_number == 15
            assert saved.latitude == pytest.approx(-12.9714)
            assert saved.longitude == pytest.approx(-38.5014)
            assert saved.speed_knots == pytest.approx(14.4)
            assert saved.course_heading == pytest.approx(248.0)
            assert saved.engine_rpm == pytest.approx(1580.0)
            assert saved.engine_temp_celsius == pytest.approx(82.0)
            assert saved.fuel_level_percent == pytest.approx(79.5)
            assert saved.network_latency_ms == pytest.approx(27.5)
            assert saved.network_rssi_dbm == -71
    finally:
        await shutdown_runtime(runtime, dispose_db=False)


async def test_explicit_idempotency_same_uuidv4_twice_writes_once_and_returns_duplicate_ignored(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Critério de aceite explícito: enviar duas vezes o mesmo UUIDv4 grava apenas 1 vez
    no banco e retorna ACK_STATUS_DUPLICADO_IGNORADO (DUPLICATE_IGNORED) no reenvio.
    """
    bridge = _InMemorySnsToSqsBridge()
    settings = ServerSettings(
        grpc_host="127.0.0.1",
        grpc_port=0,
        direct_path_enabled=True,
        decoupled_path_enabled=True,
        shutdown_grace_seconds=0.5,
    )
    runtime = await build_server(
        settings,
        session_factory=sqlite_session_factory,
        publisher=bridge,
    )
    await runtime.server.start()

    try:
        fixed_uuid = str(uuid4())
        packet = _sample_packet(message_id=fixed_uuid)

        async with grpc.aio.insecure_channel(f"127.0.0.1:{runtime.bound_port}") as channel:
            stub = telemetry_pb2_grpc.TelemetryServiceStub(channel)

            # 1º envio: aceito e persistido
            first_ack = await stub.EnviarTelemetria(packet)
            # 2º envio idêntico (mesmo UUIDv4): ignorado por idempotência
            second_ack = await stub.EnviarTelemetria(packet)

        assert first_ack.message_id == fixed_uuid
        assert first_ack.sucesso is True
        assert first_ack.duplicado is False
        assert first_ack.status == telemetry_pb2.ACK_STATUS_ACEITO

        assert second_ack.message_id == fixed_uuid
        assert second_ack.sucesso is True
        assert second_ack.duplicado is True
        assert second_ack.status == telemetry_pb2.ACK_STATUS_DUPLICADO_IGNORADO
        assert "duplicado" in second_ack.mensagem.lower()

        # Garantia estrita de apenas 1 tupla no banco e 1 publicação no SNS
        assert await _count_rows(sqlite_session_factory, UUID(fixed_uuid)) == 1
        assert await _count_rows(sqlite_session_factory) == 1
        assert len(bridge.published_events) == 1
    finally:
        await shutdown_runtime(runtime, dispose_db=False)


async def test_idempotency_survives_cold_cache_across_server_restarts_using_database(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Simula reinício/escala horizontal (cache em memória frio) validando deduplicação pelo banco."""
    packet_id = str(uuid4())
    packet = _sample_packet(message_id=packet_id)
    bridge = _InMemorySnsToSqsBridge()

    settings = ServerSettings(
        grpc_host="127.0.0.1",
        grpc_port=0,
        direct_path_enabled=True,
        decoupled_path_enabled=True,
        shutdown_grace_seconds=0.5,
    )

    # Nó 1 recebe e persiste o pacote
    runtime_node_1 = await build_server(
        settings,
        session_factory=sqlite_session_factory,
        publisher=bridge,
        idempotency=IdempotencyGuard(InMemoryIdempotencyCache(max_size=100, ttl_seconds=60.0)),
    )
    await runtime_node_1.server.start()
    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{runtime_node_1.bound_port}") as ch1:
            ack1 = await telemetry_pb2_grpc.TelemetryServiceStub(ch1).EnviarTelemetria(packet)
            assert ack1.status == telemetry_pb2.ACK_STATUS_ACEITO
            assert ack1.duplicado is False
    finally:
        await shutdown_runtime(runtime_node_1, dispose_db=False)

    # Nó 2 com cache completamente vazio recebe o mesmo UUIDv4
    runtime_node_2 = await build_server(
        settings,
        session_factory=sqlite_session_factory,
        publisher=bridge,
        idempotency=IdempotencyGuard(InMemoryIdempotencyCache(max_size=100, ttl_seconds=60.0)),
    )
    await runtime_node_2.server.start()
    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{runtime_node_2.bound_port}") as ch2:
            ack2 = await telemetry_pb2_grpc.TelemetryServiceStub(ch2).EnviarTelemetria(packet)
            assert ack2.sucesso is True
            assert ack2.duplicado is True
            assert ack2.status == telemetry_pb2.ACK_STATUS_DUPLICADO_IGNORADO
    finally:
        await shutdown_runtime(runtime_node_2, dispose_db=False)

    assert await _count_rows(sqlite_session_factory, UUID(packet_id)) == 1
    assert len(bridge.published_events) == 1


async def test_idempotency_concurrent_duplicate_rpcs_serialize_and_write_once(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Dispara 6 RPCs concorrentes com o mesmo UUIDv4 e garante apenas 1 escrita e 1 publicação SNS."""
    bridge = _InMemorySnsToSqsBridge()
    settings = ServerSettings(
        grpc_host="127.0.0.1",
        grpc_port=0,
        direct_path_enabled=True,
        decoupled_path_enabled=True,
        shutdown_grace_seconds=0.5,
    )
    runtime = await build_server(
        settings,
        session_factory=sqlite_session_factory,
        publisher=bridge,
    )
    await runtime.server.start()

    try:
        shared_uuid = str(uuid4())
        packet = _sample_packet(message_id=shared_uuid)

        async with grpc.aio.insecure_channel(f"127.0.0.1:{runtime.bound_port}") as channel:
            stub = telemetry_pb2_grpc.TelemetryServiceStub(channel)
            acks = await asyncio.gather(*(stub.EnviarTelemetria(packet) for _ in range(6)))

        accepted = [a for a in acks if a.status == telemetry_pb2.ACK_STATUS_ACEITO]
        duplicated = [a for a in acks if a.status == telemetry_pb2.ACK_STATUS_DUPLICADO_IGNORADO]

        assert len(accepted) == 1
        assert accepted[0].duplicado is False
        assert len(duplicated) == 5
        assert all(a.sucesso is True and a.duplicado is True for a in duplicated)

        assert await _count_rows(sqlite_session_factory, UUID(shared_uuid)) == 1
        assert len(bridge.published_events) == 1
    finally:
        await shutdown_runtime(runtime, dispose_db=False)


async def test_idempotency_db_on_conflict_fallback_returns_duplicate_ignored(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Valida a proteção final ON CONFLICT DO NOTHING quando o cache e a pré-checagem não bloqueiam."""
    from src.server.service import TelemetryServiceServicer

    packet = _sample_packet()

    # Pré-insere diretamente no SQLite simulando escrita concorrente de outro nó
    async with sqlite_session_factory() as session:
        repo = TelemetryRepository(session)
        from src.server.mapper import validate_and_map_packet

        mapped = validate_and_map_packet(packet)
        assert await repo.insert_packet(mapped.record) is True
        await session.commit()

    # Servicer com cache desabilitado e pré-checagem retornando False para exercitar o ON CONFLICT
    settings = ServerSettings(
        grpc_host="127.0.0.1",
        grpc_port=0,
        direct_path_enabled=True,
        decoupled_path_enabled=False,
        idempotency_cache_size=0,
    )
    servicer = TelemetryServiceServicer(
        settings=settings,
        session_factory=sqlite_session_factory,
    )

    async def _skip_precheck(_: UUID) -> bool:
        return False

    servicer._check_exists_in_db = _skip_precheck  # type: ignore[method-assign]

    server = grpc.aio.server()
    telemetry_pb2_grpc.add_TelemetryServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()

    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = telemetry_pb2_grpc.TelemetryServiceStub(channel)
            ack = await stub.EnviarTelemetria(packet)

        assert ack.sucesso is True
        assert ack.duplicado is True
        assert ack.status == telemetry_pb2.ACK_STATUS_DUPLICADO_IGNORADO
        assert await _count_rows(sqlite_session_factory, UUID(packet.message_id)) == 1
    finally:
        await server.stop(grace=0.5)


async def test_grpc_both_mode_rolls_back_sqlite_transaction_when_sns_fails(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Em modo BOTH, falha transitória no SNS faz rollback no banco e permite retry bem-sucedido."""
    bridge = _InMemorySnsToSqsBridge(fail_publish=True)
    settings = ServerSettings(
        grpc_host="127.0.0.1",
        grpc_port=0,
        direct_path_enabled=True,
        decoupled_path_enabled=True,
        shutdown_grace_seconds=0.5,
    )
    runtime = await build_server(
        settings,
        session_factory=sqlite_session_factory,
        publisher=bridge,
    )
    await runtime.server.start()

    try:
        packet = _sample_packet()
        async with grpc.aio.insecure_channel(f"127.0.0.1:{runtime.bound_port}") as channel:
            stub = telemetry_pb2_grpc.TelemetryServiceStub(channel)

            with pytest.raises(grpc.aio.AioRpcError) as exc_info:
                await stub.EnviarTelemetria(packet)
            assert exc_info.value.code() == grpc.StatusCode.UNAVAILABLE

            # Transação foi revertida: 0 registros no banco
            assert await _count_rows(sqlite_session_factory, UUID(packet.message_id)) == 0

            # SNS volta ao normal -> retry do barco deve ser aceito e persistido
            bridge.fail_publish = False
            ack = await stub.EnviarTelemetria(packet)
            assert ack.sucesso is True
            assert ack.duplicado is False
            assert ack.status == telemetry_pb2.ACK_STATUS_ACEITO

        assert await _count_rows(sqlite_session_factory, UUID(packet.message_id)) == 1
        assert len(bridge.published_events) == 1
    finally:
        await shutdown_runtime(runtime, dispose_db=False)


async def test_full_decoupled_pipeline_grpc_sns_sqs_worker_sqlite_with_idempotency(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Valida pipeline assíncrono completo: gRPC (DECOUPLED) -> SNS -> SQS -> Worker -> SQLite."""
    bridge = _InMemorySnsToSqsBridge()
    grpc_settings = ServerSettings(
        grpc_host="127.0.0.1",
        grpc_port=0,
        direct_path_enabled=False,
        decoupled_path_enabled=True,
        shutdown_grace_seconds=0.5,
    )
    runtime = await build_server(grpc_settings, publisher=bridge)
    await runtime.server.start()

    p1 = _sample_packet(boat_id="ferry-maria-bethania")
    p2 = _sample_packet(boat_id="ferry-dorival-caymmi")

    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{runtime.bound_port}") as channel:
            stub = telemetry_pb2_grpc.TelemetryServiceStub(channel)
            ack1 = await stub.EnviarTelemetria(p1, metadata=(("x-sequence-number", "101"),))
            ack2 = await stub.EnviarTelemetria(p2, metadata=(("x-sequence-number", "102"),))
            # Reenvio duplicado de p1 na borda gRPC não gera nova mensagem no SNS
            ack1_dup = await stub.EnviarTelemetria(p1, metadata=(("x-sequence-number", "101"),))

        assert ack1.status == telemetry_pb2.ACK_STATUS_ACEITO
        assert ack2.status == telemetry_pb2.ACK_STATUS_ACEITO
        assert ack1_dup.status == telemetry_pb2.ACK_STATUS_DUPLICADO_IGNORADO
        assert len(bridge.published_events) == 2
        assert len(bridge.sqs_queue) == 2

        # Simula entrega at-least-once do SQS duplicando a mensagem de p1 na fila
        duplicate_sqs_copy = dict(bridge.sqs_queue[0])
        duplicate_sqs_copy["MessageId"] = "sqs-redelivery-1"
        duplicate_sqs_copy["ReceiptHandle"] = "rh-redelivery-1"
        bridge.sqs_queue.append(duplicate_sqs_copy)

        worker_settings = WorkerSettings(
            sqs_queue_url="http://localhost:4566/000000000000/ferry-db-writer-queue",
            sqs_dlq_url="http://localhost:4566/000000000000/ferry-db-writer-queue-dlq",
            batch_size=10,
            batch_timeout_seconds=0.1,
            wait_time_seconds=0,
            max_retries=3,
        )
        worker = TelemetryBatchWorker(
            settings=worker_settings,
            session_factory=sqlite_session_factory,
            sqs_client=bridge,
        )

        inserted = await worker.process_one_batch()
        assert inserted == 2
        assert worker.metrics.records_inserted == 2
        assert worker.metrics.duplicates_ignored == 1
        assert len(bridge.deleted_handles) == 3

        assert await _count_rows(sqlite_session_factory) == 2
        async with sqlite_session_factory() as session:
            repo = TelemetryRepository(session)
            row1 = await repo.get_by_packet_id(UUID(p1.message_id))
            row2 = await repo.get_by_packet_id(UUID(p2.message_id))
            assert row1 is not None and row1.sequence_number == 101
            assert row2 is not None and row2.sequence_number == 102
    finally:
        await shutdown_runtime(runtime, dispose_db=False)
