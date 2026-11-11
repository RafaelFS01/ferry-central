"""Testes unitários para o publicador assíncrono SNS (Decoupled Path)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from botocore.exceptions import ClientError

from src.server.sns_publisher import SnsPublishError, SnsTelemetryPublisher


class _FakeBotoSnsClient:
    def __init__(self, fail_publish: bool = False) -> None:
        self.created_topics: list[str] = []
        self.published: list[dict[str, Any]] = []
        self.fail_publish = fail_publish

    def create_topic(self, Name: str) -> dict[str, str]:
        self.created_topics.append(Name)
        return {"TopicArn": f"arn:aws:sns:us-east-1:000000000000:{Name}"}

    def publish(self, **kwargs: Any) -> dict[str, str]:
        if self.fail_publish:
            raise ClientError(
                {"Error": {"Code": "InternalError", "Message": "SNS unavailable"}},
                "Publish",
            )
        self.published.append(kwargs)
        return {"MessageId": f"sns-msg-{len(self.published)}"}


async def test_sns_publisher_resolves_topic_name_once_and_publishes_json() -> None:
    fake_client = _FakeBotoSnsClient()
    publisher = SnsTelemetryPublisher(
        topic_arn=None,
        topic_name="ferry-telemetry-topic",
        boto_client=fake_client,
    )

    msg_id_1 = await publisher.publish(
        {"packet_id": "abc", "boat_id": "ferry-ivete-sangalo"},
        message_attributes={"boat_id": "ferry-ivete-sangalo"},
    )
    msg_id_2 = await publisher.publish({"packet_id": "def", "boat_id": "ferry-ivete-sangalo"})

    assert msg_id_1 == "sns-msg-1"
    assert msg_id_2 == "sns-msg-2"
    assert fake_client.created_topics == ["ferry-telemetry-topic"]
    assert publisher.topic_arn == "arn:aws:sns:us-east-1:000000000000:ferry-telemetry-topic"

    first = fake_client.published[0]
    assert first["TopicArn"] == publisher.topic_arn
    assert json.loads(first["Message"]) == {
        "packet_id": "abc",
        "boat_id": "ferry-ivete-sangalo",
    }
    assert first["MessageAttributes"] == {
        "boat_id": {"DataType": "String", "StringValue": "ferry-ivete-sangalo"}
    }


async def test_sns_publisher_wraps_botocore_errors_as_sns_publish_error() -> None:
    fake_client = _FakeBotoSnsClient(fail_publish=True)
    publisher = SnsTelemetryPublisher(
        topic_arn="arn:aws:sns:us-east-1:000000000000:ferry-telemetry-topic",
        boto_client=fake_client,
    )

    with pytest.raises(SnsPublishError, match="Falha ao publicar"):
        await publisher.publish({"packet_id": "abc"})

