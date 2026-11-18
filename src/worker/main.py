"""Ponto de entrada do serviço consumidor SQS em lote (SCRUM-17)."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any

from src.database.session import create_async_db_engine, create_session_factory
from src.worker.config import WorkerSettings
from src.worker.consumer import TelemetryBatchWorker
from src.worker.sqs_client import BotoSqsClient

logger = logging.getLogger("src.worker.main")


def configure_logging(level: str = "INFO") -> None:
    """Configura logging formatado padrão do worker."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


async def run_worker(settings: WorkerSettings | None = None) -> None:
    """Inicializa conexões e executa o loop do consumidor com graceful shutdown."""
    cfg = settings or WorkerSettings.from_env()
    configure_logging(cfg.log_level)

    logger.info("Iniciando serviço de background Worker SQS -> PostgreSQL (Python 3.14)...")
    logger.info("Fila SQS: %s", cfg.sqs_queue_url)
    logger.info("DLQ SQS: %s", cfg.sqs_dlq_url)
    logger.info("Tamanho do micro-batch: %d registros", cfg.batch_size)
    logger.info("Janela temporal máxima: %.1f segundos", cfg.batch_timeout_seconds)
    logger.info("WaitTimeSeconds SQS: %d segundos", cfg.wait_time_seconds)

    engine = create_async_db_engine(cfg.to_database_settings())
    session_factory = create_session_factory(engine)

    sqs_client = BotoSqsClient(
        region_name=cfg.aws_region,
        endpoint_url=cfg.aws_endpoint_url,
    )

    worker = TelemetryBatchWorker(
        settings=cfg,
        session_factory=session_factory,
        sqs_client=sqs_client,
    )

    loop = asyncio.get_running_loop()

    def _signal_handler(*_: Any) -> None:
        logger.info("Sinal do sistema operacional interceptado. Solicitando parada...")
        worker.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except (NotImplementedError, RuntimeError):
            # No Windows, add_signal_handler pode não ser suportado para determinados loops
            signal.signal(sig, lambda *args: worker.stop())

    try:
        await worker.run()
    finally:
        logger.info("Finalizando recursos do worker...")
        await worker.close()
        await sqs_client.close()
        await engine.dispose()
        logger.info("Worker finalizado com sucesso.")


def main() -> None:
    """Entrypoint de execução do processo."""
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Interrupção manual pelo teclado.")
        sys.exit(0)


if __name__ == "__main__":
    main()
