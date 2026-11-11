"""Ponto de entrada do servidor gRPC assíncrono (grpc.aio) do Nó Central."""

from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database.session import dispose_engine, get_session_factory
from src.proto import telemetry_pb2, telemetry_pb2_grpc
from src.server.config import ServerSettings
from src.server.idempotency import IdempotencyGuard, InMemoryIdempotencyCache
from src.server.service import TelemetryServiceServicer
from src.server.sns_publisher import SnsTelemetryPublisher, TelemetryPublisher

logger = logging.getLogger(__name__)

TELEMETRY_SERVICE_NAME = telemetry_pb2.DESCRIPTOR.services_by_name[
    "TelemetryService"
].full_name


@dataclass(slots=True)
class GrpcServerRuntime:
    """Agrupa instâncias do servidor gRPC e recursos gerenciados no ciclo de vida."""

    server: grpc.aio.Server
    health_servicer: health.aio.HealthServicer
    publisher: TelemetryPublisher | None
    settings: ServerSettings
    bound_port: int


def configure_logging(level: str = "INFO") -> None:
    """Configura logging estruturado padrão para o servidor Central."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _default_server_options(settings: ServerSettings) -> list[tuple[str, int]]:
    return [
        ("grpc.keepalive_time_ms", 30_000),
        ("grpc.keepalive_timeout_ms", 10_000),
        ("grpc.keepalive_permit_without_calls", 1),
        ("grpc.http2.max_pings_without_data", 0),
        ("grpc.http2.min_ping_interval_without_data_ms", 10_000),
        ("grpc.max_receive_message_length", settings.max_message_length_bytes),
    ]


async def build_server(
    settings: ServerSettings | None = None,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    publisher: TelemetryPublisher | None = None,
    idempotency: IdempotencyGuard | None = None,
) -> GrpcServerRuntime:
    """Constrói e faz bind do servidor grpc.aio com TelemetryService e HealthCheck."""
    cfg = settings or ServerSettings.from_env()

    resolved_session_factory = session_factory
    if cfg.direct_path_enabled and resolved_session_factory is None:
        resolved_session_factory = get_session_factory()

    resolved_publisher = publisher
    if cfg.decoupled_path_enabled and resolved_publisher is None:
        resolved_publisher = SnsTelemetryPublisher(
            topic_arn=cfg.sns_topic_arn,
            topic_name=cfg.sns_topic_name,
            region_name=cfg.aws_region,
            endpoint_url=cfg.aws_endpoint_url,
        )

    resolved_idempotency = idempotency or IdempotencyGuard(
        cache=InMemoryIdempotencyCache(
            max_size=cfg.idempotency_cache_size,
            ttl_seconds=cfg.idempotency_cache_ttl_seconds,
        )
    )

    server = grpc.aio.server(options=_default_server_options(cfg))
    servicer = TelemetryServiceServicer(
        settings=cfg,
        session_factory=resolved_session_factory,
        publisher=resolved_publisher,
        idempotency=resolved_idempotency,
    )
    telemetry_pb2_grpc.add_TelemetryServiceServicer_to_server(servicer, server)

    health_servicer = health.aio.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    await health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    await health_servicer.set(
        TELEMETRY_SERVICE_NAME,
        health_pb2.HealthCheckResponse.SERVING,
    )

    bound_port = server.add_insecure_port(cfg.bind_address)
    if bound_port == 0:
        raise RuntimeError(
            f"Não foi possível fazer bind gRPC no endereço {cfg.bind_address}."
        )

    return GrpcServerRuntime(
        server=server,
        health_servicer=health_servicer,
        publisher=resolved_publisher,
        settings=cfg,
        bound_port=bound_port,
    )


async def shutdown_runtime(
    runtime: GrpcServerRuntime,
    *,
    dispose_db: bool = True,
) -> None:
    """Executa graceful shutdown drenando RPCs e encerrando conexões externas."""
    await runtime.health_servicer.set("", health_pb2.HealthCheckResponse.NOT_SERVING)
    await runtime.health_servicer.set(
        TELEMETRY_SERVICE_NAME,
        health_pb2.HealthCheckResponse.NOT_SERVING,
    )
    await runtime.server.stop(grace=runtime.settings.shutdown_grace_seconds)

    if runtime.publisher is not None:
        await runtime.publisher.close()

    if dispose_db:
        await dispose_engine()


async def serve(settings: ServerSettings | None = None) -> None:
    """Inicializa o servidor gRPC assíncrono e aguarda sinais de encerramento."""
    cfg = settings or ServerSettings.from_env()
    configure_logging(cfg.log_level)

    runtime = await build_server(cfg)
    await runtime.server.start()
    logger.info(
        "Servidor gRPC Central escutando em %s (porta=%d, direct=%s, decoupled=%s, sns_topic=%s)",
        cfg.bind_address,
        runtime.bound_port,
        cfg.direct_path_enabled,
        cfg.decoupled_path_enabled,
        cfg.sns_topic_arn or cfg.sns_topic_name,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Windows ProactorEventLoop não suporta add_signal_handler.
            pass

    try:
        server_task = asyncio.create_task(runtime.server.wait_for_termination())
        stop_task = asyncio.create_task(stop_event.wait())
        _, pending = await asyncio.wait(
            {server_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Interrupção recebida, iniciando graceful shutdown...")
    finally:
        logger.info("Encerrando servidor gRPC Central...")
        await shutdown_runtime(runtime, dispose_db=cfg.direct_path_enabled)
        logger.info("Servidor gRPC Central encerrado com sucesso.")


def main() -> None:
    """Entrypoint CLI do servidor gRPC Central."""
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

