"""Publicador assíncrono para o tópico Amazon SNS (Decoupled Path)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any, Protocol

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError


class SnsPublishError(RuntimeError):
    """Erro transitório ou de configuração ao publicar telemetria no SNS."""


class TelemetryPublisher(Protocol):
    """Contrato assíncrono para publicação de eventos de telemetria."""

    async def publish(
        self,
        payload: Mapping[str, Any],
        message_attributes: Mapping[str, str] | None = None,
    ) -> str:
        """Publica uma mensagem de telemetria e retorna o identificador do broker."""

    async def close(self) -> None:
        """Libera recursos subjacentes do cliente."""


class SnsTelemetryPublisher:
    """Publica pacotes de telemetria em tópico Amazon SNS sem bloquear o loop gRPC."""

    def __init__(
        self,
        topic_arn: str | None = None,
        topic_name: str = "ferry-telemetry-topic",
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
        boto_client: Any | None = None,
    ) -> None:
        if not topic_arn and not topic_name:
            raise ValueError("Informe sns_topic_arn ou sns_topic_name para publicar no SNS.")

        self._topic_arn = topic_arn
        self._topic_name = topic_name
        self._region_name = region_name
        self._endpoint_url = endpoint_url
        self._resolve_lock = asyncio.Lock()
        self._owns_client = boto_client is None
        self._client = boto_client or boto3.client(
            "sns",
            region_name=region_name,
            endpoint_url=endpoint_url,
            config=BotoConfig(
                max_pool_connections=50,
                connect_timeout=2.0,
                read_timeout=3.0,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )

    @property
    def topic_arn(self) -> str | None:
        """Retorna o ARN resolvido do tópico SNS, se já inicializado."""
        return self._topic_arn

    def _resolve_topic_arn_sync(self) -> str:
        response = self._client.create_topic(Name=self._topic_name)
        arn = response.get("TopicArn")
        if not arn:
            raise SnsPublishError(
                f"Resposta SNS sem TopicArn ao resolver tópico {self._topic_name!r}."
            )
        return str(arn)

    async def _ensure_topic_arn(self) -> str:
        if self._topic_arn:
            return self._topic_arn

        async with self._resolve_lock:
            if self._topic_arn:
                return self._topic_arn
            try:
                self._topic_arn = await asyncio.to_thread(self._resolve_topic_arn_sync)
            except (BotoCoreError, ClientError, OSError) as exc:
                raise SnsPublishError(
                    f"Falha ao resolver ARN do tópico SNS {self._topic_name!r}: {exc}"
                ) from exc
            return self._topic_arn

    def _publish_sync(
        self,
        topic_arn: str,
        serialized_body: str,
        attributes: dict[str, dict[str, str]],
    ) -> str:
        kwargs: dict[str, Any] = {
            "TopicArn": topic_arn,
            "Message": serialized_body,
        }
        if attributes:
            kwargs["MessageAttributes"] = attributes

        response = self._client.publish(**kwargs)
        return str(response.get("MessageId", ""))

    async def publish(
        self,
        payload: Mapping[str, Any],
        message_attributes: Mapping[str, str] | None = None,
    ) -> str:
        """Serializa o payload em JSON e publica no tópico SNS em thread pool dedicada."""
        topic_arn = await self._ensure_topic_arn()
        serialized_body = json.dumps(
            dict(payload),
            separators=(",", ":"),
            ensure_ascii=False,
        )
        formatted_attrs = {
            key: {"DataType": "String", "StringValue": str(value)}
            for key, value in (message_attributes or {}).items()
            if value
        }

        try:
            return await asyncio.to_thread(
                self._publish_sync,
                topic_arn,
                serialized_body,
                formatted_attrs,
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise SnsPublishError(
                f"Falha ao publicar telemetria no tópico SNS {topic_arn}: {exc}"
            ) from exc

    async def close(self) -> None:
        """Fecha conexões HTTP do cliente botocore se criado internamente."""
        if self._owns_client and hasattr(self._client, "close"):
            await asyncio.to_thread(self._client.close)

