"""Cliente assíncrono para operações de mensageria SQS / DLQ."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

SQS_MAX_DELETE_BATCH_SIZE = 10


class SqsClientProtocol(Protocol):
    """Contrato assíncrono para interação com filas Amazon SQS."""

    async def receive_messages(
        self,
        queue_url: str,
        max_number: int = 10,
        wait_time_seconds: int = 20,
    ) -> list[dict[str, Any]]:
        """Lê mensagens da fila via long-polling assíncrono."""

    async def delete_messages_batch(
        self,
        queue_url: str,
        receipt_handles: Sequence[str],
    ) -> None:
        """Exclui mensagens da fila em lotes de até 10 por requisição."""

    async def change_message_visibility(
        self,
        queue_url: str,
        receipt_handle: str,
        visibility_timeout: int = 0,
    ) -> None:
        """Altera a visibilidade de uma mensagem para forçar reprocessamento imediato."""

    async def send_message(
        self,
        queue_url: str,
        message_body: str,
        message_attributes: Mapping[str, Any] | None = None,
    ) -> str:
        """Envia mensagem para fila ou DLQ."""

    async def close(self) -> None:
        """Libera conexões e recursos subjacentes do cliente."""


class BotoSqsClient:
    """Implementação assíncrona do cliente SQS baseada em boto3 e thread pool."""

    def __init__(
        self,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
        boto_client: Any | None = None,
    ) -> None:
        self._region_name = region_name
        self._endpoint_url = endpoint_url
        self._owns_client = boto_client is None
        self._client = boto_client or boto3.client(
            "sqs",
            region_name=region_name,
            endpoint_url=endpoint_url,
            config=BotoConfig(
                max_pool_connections=50,
                connect_timeout=3.0,
                read_timeout=25.0,  # Maior que os 20s de long-polling
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def _receive_messages_sync(
        self,
        queue_url: str,
        max_number: int,
        wait_time_seconds: int,
    ) -> list[dict[str, Any]]:
        response = self._client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=min(max_number, 10),
            WaitTimeSeconds=wait_time_seconds,
            AttributeNames=["ApproximateReceiveCount", "SentTimestamp"],
            MessageAttributeNames=["All"],
        )
        return list(response.get("Messages", []))

    async def receive_messages(
        self,
        queue_url: str,
        max_number: int = 10,
        wait_time_seconds: int = 20,
    ) -> list[dict[str, Any]]:
        """Lê mensagens via long-polling assíncrono."""
        try:
            return await asyncio.to_thread(
                self._receive_messages_sync,
                queue_url,
                max_number,
                wait_time_seconds,
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            logger.error("Falha ao ler mensagens da fila SQS %s: %s", queue_url, exc)
            raise

    def _delete_chunk_sync(self, queue_url: str, chunk: list[str]) -> None:
        entries = [{"Id": str(idx), "ReceiptHandle": handle} for idx, handle in enumerate(chunk)]
        response = self._client.delete_message_batch(QueueUrl=queue_url, Entries=entries)
        failed = response.get("Failed", [])
        if failed:
            logger.warning(
                "Falha na exclusão de %d mensagens da fila %s: %s",
                len(failed),
                queue_url,
                failed,
            )

    async def delete_messages_batch(
        self,
        queue_url: str,
        receipt_handles: Sequence[str],
    ) -> None:
        """Exclui mensagens em lotes de até 10 handles."""
        if not receipt_handles:
            return

        unique_handles = list(dict.fromkeys(receipt_handles))
        for start in range(0, len(unique_handles), SQS_MAX_DELETE_BATCH_SIZE):
            chunk = unique_handles[start : start + SQS_MAX_DELETE_BATCH_SIZE]
            try:
                await asyncio.to_thread(self._delete_chunk_sync, queue_url, chunk)
            except (BotoCoreError, ClientError, OSError) as exc:
                logger.error("Erro ao deletar lote de mensagens da fila %s: %s", queue_url, exc)
                raise

    def _change_visibility_sync(
        self,
        queue_url: str,
        receipt_handle: str,
        visibility_timeout: int,
    ) -> None:
        self._client.change_message_visibility(
            QueueUrl=queue_url,
            ReceiptHandle=receipt_handle,
            VisibilityTimeout=visibility_timeout,
        )

    async def change_message_visibility(
        self,
        queue_url: str,
        receipt_handle: str,
        visibility_timeout: int = 0,
    ) -> None:
        """Altera tempo de visibilidade assincronamente."""
        try:
            await asyncio.to_thread(
                self._change_visibility_sync,
                queue_url,
                receipt_handle,
                visibility_timeout,
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            logger.warning(
                "Falha ao ajustar visibilidade de mensagem da fila %s: %s", queue_url, exc
            )
            raise

    def _send_message_sync(
        self,
        queue_url: str,
        message_body: str,
        message_attributes: Mapping[str, Any] | None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "QueueUrl": queue_url,
            "MessageBody": message_body,
        }
        if message_attributes:
            kwargs["MessageAttributes"] = dict(message_attributes)

        response = self._client.send_message(**kwargs)
        return str(response.get("MessageId", ""))

    async def send_message(
        self,
        queue_url: str,
        message_body: str,
        message_attributes: Mapping[str, Any] | None = None,
    ) -> str:
        """Envia mensagem assincronamente para a fila ou DLQ."""
        try:
            return await asyncio.to_thread(
                self._send_message_sync,
                queue_url,
                message_body,
                message_attributes,
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            logger.error("Falha ao enviar mensagem para %s: %s", queue_url, exc)
            raise

    async def close(self) -> None:
        """Libera cliente subjacente caso gerenciado internamente."""
        if self._owns_client and hasattr(self._client, "close"):
            await asyncio.to_thread(self._client.close)
