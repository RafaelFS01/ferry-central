"""Consumidor assíncrono em micro-lotes da fila SQS para PostgreSQL (SCRUM-17)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database.repository import TelemetryRecordInput, TelemetryRepository
from src.worker.config import WorkerSettings
from src.worker.parser import CorruptedMessageError, parse_sqs_message
from src.worker.sqs_client import BotoSqsClient, SqsClientProtocol

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WorkerMetrics:
    """Métricas em memória de ingestão do consumidor SQS."""

    messages_received: int = 0
    records_inserted: int = 0
    duplicates_ignored: int = 0
    corrupted_messages: int = 0
    dlq_forwarded: int = 0
    batches_flushed: int = 0
    db_failures: int = 0


@dataclass(slots=True)
class _PendingItem:
    record: TelemetryRecordInput
    receipt_handle: str
    message_id: str


class TelemetryBatchWorker:
    """Consome pacotes de telemetria da fila SQS com agregação em lote e persistência idempotente."""

    def __init__(
        self,
        settings: WorkerSettings,
        session_factory: async_sessionmaker[AsyncSession],
        sqs_client: SqsClientProtocol | None = None,
        repository_factory: Callable[[AsyncSession], TelemetryRepository] = TelemetryRepository,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._owns_sqs = sqs_client is None
        self._sqs: SqsClientProtocol = sqs_client or BotoSqsClient(
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        )
        self._repository_factory = repository_factory
        self._stop_event = asyncio.Event()
        self._metrics = WorkerMetrics()

    @property
    def metrics(self) -> WorkerMetrics:
        """Retorna instantâneo das métricas de processamento."""
        return self._metrics

    @property
    def is_running(self) -> bool:
        """Indica se o consumidor está ativo."""
        return not self._stop_event.is_set()

    def stop(self) -> None:
        """Sinaliza parada cooperativa do loop consumidor."""
        logger.info("Sinal de parada recebido. Encerrando consumidor TelemetryBatchWorker...")
        self._stop_event.set()

    async def _handle_corrupted_message(
        self,
        msg: dict[str, Any],
        receive_count: int,
        error_reason: str,
    ) -> None:
        """Trata mensagens corrompidas com retries ou encaminhamento para DLQ."""
        self._metrics.corrupted_messages += 1
        message_id = str(msg.get("MessageId", ""))
        receipt_handle = str(msg.get("ReceiptHandle", ""))
        body = str(msg.get("Body", ""))

        if receive_count >= self._settings.max_retries:
            dlq_url = self._settings.sqs_dlq_url
            if dlq_url:
                logger.error(
                    "Mensagem corrompida esgotou tentativas (%d/%d): msg_id=%s. Encaminhando para DLQ: %s",
                    receive_count,
                    self._settings.max_retries,
                    message_id,
                    dlq_url,
                )
                try:
                    await self._sqs.send_message(
                        queue_url=dlq_url,
                        message_body=body,
                        message_attributes={
                            "x-error-reason": {
                                "DataType": "String",
                                "StringValue": error_reason[:256],
                            },
                            "x-receive-count": {
                                "DataType": "Number",
                                "StringValue": str(receive_count),
                            },
                            "x-original-message-id": {
                                "DataType": "String",
                                "StringValue": message_id,
                            },
                        },
                    )
                    self._metrics.dlq_forwarded += 1
                    # Exclui da fila original somente após confirmação de entrega na DLQ
                    await self._sqs.delete_messages_batch(
                        self._settings.sqs_queue_url,
                        [receipt_handle],
                    )
                except Exception as dlq_err:
                    logger.exception(
                        "Falha ao encaminhar mensagem %s para a DLQ %s: %s",
                        message_id,
                        dlq_url,
                        dlq_err,
                    )
            else:
                logger.warning(
                    "Mensagem corrompida %s esgotou tentativas (%d/%d), mas SQS_DLQ_URL não configurada. "
                    "Mantida na fila para redrive nativo da nuvem.",
                    message_id,
                    receive_count,
                    self._settings.max_retries,
                )
        else:
            logger.warning(
                "Mensagem corrompida %s (tentativa %d/%d): %s. Reagendando visibilidade.",
                message_id,
                receive_count,
                self._settings.max_retries,
                error_reason,
            )
            try:
                await self._sqs.change_message_visibility(
                    queue_url=self._settings.sqs_queue_url,
                    receipt_handle=receipt_handle,
                    visibility_timeout=0,
                )
            except Exception as vis_err:
                logger.warning(
                    "Falha ao ajustar visibilidade de mensagem %s: %s",
                    message_id,
                    vis_err,
                )

    async def _process_single_message(
        self,
        msg: dict[str, Any],
    ) -> _PendingItem | None:
        """Deserializa pacote SQS e trata mensagens defeituosas."""
        self._metrics.messages_received += 1
        message_id = str(msg.get("MessageId", ""))
        receipt_handle = str(msg.get("ReceiptHandle", ""))
        body = msg.get("Body", "")
        attrs = msg.get("Attributes", {})
        receive_count = int(attrs.get("ApproximateReceiveCount", "1"))

        try:
            record = parse_sqs_message(body)
            return _PendingItem(
                record=record,
                receipt_handle=receipt_handle,
                message_id=message_id,
            )
        except CorruptedMessageError as exc:
            await self._handle_corrupted_message(msg, receive_count, str(exc))
            return None

    async def _flush_batch(self, batch: Sequence[_PendingItem]) -> int:
        """Grava o lote atomicamente no PostgreSQL e exclui do SQS apenas após commit."""
        if not batch:
            return 0

        records = [item.record for item in batch]
        receipt_handles = [item.receipt_handle for item in batch]

        async with self._session_factory() as session:
            try:
                repo = self._repository_factory(session)
                inserted = await repo.insert_batch(records)
                await session.commit()
            except SQLAlchemyError as exc:
                self._metrics.db_failures += 1
                logger.error(
                    "Falha ao comitar lote no PostgreSQL (%d registros). Realizando rollback: %s",
                    len(batch),
                    exc,
                )
                try:
                    await session.rollback()
                except Exception:
                    logger.debug("Erro secundário durante rollback.", exc_info=True)
                # Não exclui mensagens do SQS para reprocessamento
                raise

        # Commit bem-sucedido no PostgreSQL: agora exclui do SQS
        try:
            await self._sqs.delete_messages_batch(
                self._settings.sqs_queue_url,
                receipt_handles,
            )
        except Exception as exc:
            logger.error(
                "Lote commitado no DB, mas falhou ao excluir %d mensagens do SQS: %s",
                len(receipt_handles),
                exc,
            )
            # Idempotência (ON CONFLICT DO NOTHING) absorve qualquer duplicata em caso de retry

        duplicates = len(batch) - inserted
        self._metrics.records_inserted += inserted
        self._metrics.duplicates_ignored += duplicates
        self._metrics.batches_flushed += 1

        logger.info(
            "Lote persistido com sucesso: total=%d inseridos=%d duplicados=%d",
            len(batch),
            inserted,
            duplicates,
        )
        return inserted

    async def _collect_batch(
        self,
        batch_size: int,
        timeout_seconds: float,
    ) -> list[_PendingItem]:
        """Agrupa mensagens em lotes de até batch_size ou até estourar a janela de tempo."""
        collected: list[_PendingItem] = []

        if self._stop_event.is_set():
            return collected

        # 1. Primeira leitura (long-polling até wait_time_seconds)
        messages = await self._sqs.receive_messages(
            queue_url=self._settings.sqs_queue_url,
            max_number=min(10, batch_size),
            wait_time_seconds=self._settings.wait_time_seconds,
        )
        if not messages:
            return collected

        batch_start = time.monotonic()
        for msg in messages:
            item = await self._process_single_message(msg)
            if item is not None:
                collected.append(item)
                if len(collected) >= batch_size:
                    return collected

        # Se todas as mensagens recebidas eram corrompidas ou foram descartadas
        if not collected:
            return collected

        # 2. Acumulação secundária respeitando o timeout_seconds da janela
        while not self._stop_event.is_set():
            elapsed = time.monotonic() - batch_start
            remaining = timeout_seconds - elapsed
            if remaining <= 0 or len(collected) >= batch_size:
                break

            needed = min(10, batch_size - len(collected))
            wait_s = max(0, min(int(remaining), 20))

            messages = await self._sqs.receive_messages(
                queue_url=self._settings.sqs_queue_url,
                max_number=needed,
                wait_time_seconds=wait_s,
            )
            if messages:
                for msg in messages:
                    item = await self._process_single_message(msg)
                    if item is not None:
                        collected.append(item)
                        if len(collected) >= batch_size:
                            break
            else:
                elapsed_now = time.monotonic() - batch_start
                remaining_now = timeout_seconds - elapsed_now
                if remaining_now > 0:
                    await asyncio.sleep(min(0.05, remaining_now))

        return collected

    async def process_one_batch(self) -> int:
        """Executa um ciclo completo de coleta e persistência em lote."""
        batch = await self._collect_batch(
            batch_size=self._settings.batch_size,
            timeout_seconds=self._settings.batch_timeout_seconds,
        )
        if not batch:
            return 0
        return await self._flush_batch(batch)

    async def run(self) -> None:
        """Loop principal do consumidor de telemetria até sinal de parada."""
        logger.info(
            "Iniciando consumidor SQS TelemetryBatchWorker (Fila: %s, Batch: %d, Janela: %.1fs, LongPoll: %ds)...",
            self._settings.sqs_queue_url,
            self._settings.batch_size,
            self._settings.batch_timeout_seconds,
            self._settings.wait_time_seconds,
        )

        while not self._stop_event.is_set():
            try:
                await self.process_one_batch()
            except asyncio.CancelledError:
                logger.info("Tarefa do consumidor cancelada.")
                break
            except Exception as exc:
                logger.error("Erro inesperado no ciclo de processamento do lote: %s", exc)
                # Pausa breve para não saturar CPU em erros transitórios
                await asyncio.sleep(1.0)

        logger.info("Consumidor encerrado. Métricas finais: %s", self._metrics)

    async def close(self) -> None:
        """Libera recursos gerenciados."""
        self.stop()
        if self._owns_sqs:
            await self._sqs.close()
