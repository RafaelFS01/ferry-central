"""Implementação assíncrona do servicer gRPC TelemetryService."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from uuid import UUID

import grpc
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database.repository import TelemetryRecordInput, TelemetryRepository
from src.proto import telemetry_pb2, telemetry_pb2_grpc
from src.server.config import ServerSettings
from src.server.idempotency import (
    IdempotencyGuard,
    InMemoryIdempotencyCache,
    InvalidPacketIdError,
)
from src.server.mapper import (
    MappedTelemetry,
    TelemetryValidationError,
    validate_and_map_packet,
)
from src.server.sns_publisher import SnsPublishError, TelemetryPublisher

logger = logging.getLogger(__name__)


def _now_epoch_ms() -> int:
    return time.time_ns() // 1_000_000


def _build_ack(
    packet_id: UUID,
    *,
    sucesso: bool,
    duplicado: bool,
    mensagem: str,
    status: telemetry_pb2.AckStatus,
) -> telemetry_pb2.TelemetryAck:
    return telemetry_pb2.TelemetryAck(
        message_id=str(packet_id),
        sucesso=sucesso,
        duplicado=duplicado,
        processado_em=_now_epoch_ms(),
        mensagem=mensagem,
        status=status,
    )


class TelemetryServiceServicer(telemetry_pb2_grpc.TelemetryServiceServicer):
    """Servicer RPC unário para ingestão concorrente e idempotente de telemetria."""

    def __init__(
        self,
        settings: ServerSettings,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        publisher: TelemetryPublisher | None = None,
        idempotency: IdempotencyGuard | None = None,
        repository_factory: Callable[[AsyncSession], TelemetryRepository] = TelemetryRepository,
    ) -> None:
        if not settings.direct_path_enabled and not settings.decoupled_path_enabled:
            raise ValueError(
                "Pelo menos um caminho de ingestão (direct ou decoupled) deve estar habilitado."
            )
        if settings.direct_path_enabled and session_factory is None:
            raise ValueError(
                "session_factory é obrigatório quando o caminho direto (PostgreSQL) está ativo."
            )
        if settings.decoupled_path_enabled and publisher is None:
            raise ValueError(
                "publisher é obrigatório quando o caminho desacoplado (SNS) está ativo."
            )

        self._settings = settings
        self._session_factory = session_factory
        self._publisher = publisher
        self._repository_factory = repository_factory
        self._idempotency = idempotency or IdempotencyGuard(
            cache=InMemoryIdempotencyCache(
                max_size=settings.idempotency_cache_size,
                ttl_seconds=settings.idempotency_cache_ttl_seconds,
            )
        )

    async def _check_exists_in_db(self, packet_id: UUID) -> bool:
        assert self._session_factory is not None
        async with self._session_factory() as session:
            repo = self._repository_factory(session)
            return await repo.exists_packet(packet_id)

    async def _persist_direct(
        self,
        session: AsyncSession,
        record: TelemetryRecordInput,
    ) -> bool:
        repo = self._repository_factory(session)
        return await repo.insert_packet(record)

    async def _publish_decoupled(self, mapped: MappedTelemetry) -> str:
        assert self._publisher is not None
        return await self._publisher.publish(
            mapped.sns_payload,
            message_attributes=mapped.sns_attributes,
        )

    async def EnviarTelemetria(
        self,
        request: telemetry_pb2.TelemetryPacket,
        context: grpc.aio.ServicerContext,
    ) -> telemetry_pb2.TelemetryAck:
        """Recebe TelemetryPacket, aplica deduplicação idempotente e executa ingestão."""
        try:
            metadata = context.invocation_metadata()
            mapped = validate_and_map_packet(request, metadata=metadata)
        except (InvalidPacketIdError, TelemetryValidationError) as exc:
            logger.warning("Pacote rejeitado na validação: %s", exc)
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            return telemetry_pb2.TelemetryAck()

        try:
            async with self._idempotency.lock_packet(mapped.packet_id):
                db_checker = (
                    self._check_exists_in_db
                    if self._settings.direct_path_enabled
                    else None
                )
                if await self._idempotency.is_duplicate(mapped.packet_id, db_checker):
                    logger.info(
                        "Pacote duplicado ignorado: packet_id=%s boat_id=%s",
                        mapped.packet_id,
                        mapped.boat_id,
                    )
                    return _build_ack(
                        mapped.packet_id,
                        sucesso=True,
                        duplicado=True,
                        mensagem="Pacote duplicado ignorado (idempotência).",
                        status=telemetry_pb2.ACK_STATUS_DUPLICADO_IGNORADO,
                    )

                inserted_in_db = True
                if self._settings.direct_path_enabled:
                    assert self._session_factory is not None
                    async with self._session_factory() as session:
                        try:
                            if self._settings.decoupled_path_enabled:
                                direct_res, decoupled_res = await asyncio.gather(
                                    self._persist_direct(session, mapped.record),
                                    self._publish_decoupled(mapped),
                                    return_exceptions=True,
                                )
                                for outcome in (direct_res, decoupled_res):
                                    if isinstance(outcome, asyncio.CancelledError):
                                        raise outcome
                                for outcome in (direct_res, decoupled_res):
                                    if isinstance(outcome, BaseException):
                                        raise outcome
                                inserted_in_db = bool(direct_res)
                            else:
                                inserted_in_db = await self._persist_direct(
                                    session, mapped.record
                                )
                            await session.commit()
                        except BaseException:
                            try:
                                await session.rollback()
                            except Exception:
                                logger.debug(
                                    "Falha secundária ao executar rollback da sessão para packet_id=%s.",
                                    mapped.packet_id,
                                    exc_info=True,
                                )
                            raise
                else:
                    await self._publish_decoupled(mapped)

                self._idempotency.mark_processed(mapped.packet_id)

                if not inserted_in_db:
                    logger.info(
                        "Pacote duplicado detectado na escrita concorrente: packet_id=%s boat_id=%s",
                        mapped.packet_id,
                        mapped.boat_id,
                    )
                    return _build_ack(
                        mapped.packet_id,
                        sucesso=True,
                        duplicado=True,
                        mensagem="Pacote duplicado ignorado (idempotência).",
                        status=telemetry_pb2.ACK_STATUS_DUPLICADO_IGNORADO,
                    )

                logger.debug(
                    "Telemetria ingerida: packet_id=%s boat_id=%s direct=%s decoupled=%s",
                    mapped.packet_id,
                    mapped.boat_id,
                    self._settings.direct_path_enabled,
                    self._settings.decoupled_path_enabled,
                )
                return _build_ack(
                    mapped.packet_id,
                    sucesso=True,
                    duplicado=False,
                    mensagem="Telemetria ingerida com sucesso.",
                    status=telemetry_pb2.ACK_STATUS_ACEITO,
                )

        except asyncio.CancelledError:
            logger.warning(
                "RPC cancelada durante processamento: packet_id=%s boat_id=%s",
                mapped.packet_id,
                mapped.boat_id,
            )
            raise
        except (SQLAlchemyError, SnsPublishError, OSError, TimeoutError) as exc:
            logger.error(
                "Falha transitória de infraestrutura na ingestão: packet_id=%s boat_id=%s erro=%s",
                mapped.packet_id,
                mapped.boat_id,
                exc,
            )
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                "Serviço temporariamente indisponível para persistência ou mensageria.",
            )
            return telemetry_pb2.TelemetryAck()
        except Exception:
            logger.exception(
                "Erro interno inesperado ao processar pacote: packet_id=%s boat_id=%s",
                mapped.packet_id,
                mapped.boat_id,
            )
            await context.abort(
                grpc.StatusCode.INTERNAL,
                "Erro interno inesperado ao processar telemetria.",
            )
            return telemetry_pb2.TelemetryAck()

