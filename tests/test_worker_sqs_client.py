"""Testes unitários para o cliente assíncrono SQS."""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from src.worker.sqs_client import BotoSqsClient


class _FakeBotoSqs:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.received_calls: list[dict[str, Any]] = []
        self.deleted_batches: list[dict[str, Any]] = []
        self.visibility_changes: list[dict[str, Any]] = []
        self.sent_messages: list[dict[str, Any]] = []

    def receive_message(self, **kwargs: Any) -> dict[str, Any]:
        if self.should_fail:
            raise ClientError({"Error": {"Code": "500", "Message": "SQS error"}}, "Receive")
        self.received_calls.append(kwargs)
        return {
            "Messages": [
                {
                    "MessageId": "msg-1",
                    "ReceiptHandle": "rh-1",
                    "Body": '{"packet_id": "123"}',
                    "Attributes": {"ApproximateReceiveCount": "1"},
                }
            ]
        }

    def delete_message_batch(self, **kwargs: Any) -> dict[str, Any]:
        if self.should_fail:
            raise ClientError({"Error": {"Code": "500", "Message": "SQS error"}}, "Delete")
        self.deleted_batches.append(kwargs)
        return {"Successful": kwargs.get("Entries", [])}

    def change_message_visibility(self, **kwargs: Any) -> dict[str, Any]:
        if self.should_fail:
            raise ClientError({"Error": {"Code": "500", "Message": "SQS error"}}, "ChangeVis")
        self.visibility_changes.append(kwargs)
        return {}

    def send_message(self, **kwargs: Any) -> dict[str, Any]:
        if self.should_fail:
            raise ClientError({"Error": {"Code": "500", "Message": "SQS error"}}, "Send")
        self.sent_messages.append(kwargs)
        return {"MessageId": f"dlq-msg-{len(self.sent_messages)}"}


async def test_sqs_client_receive_messages() -> None:
    fake_boto = _FakeBotoSqs()
    client = BotoSqsClient(boto_client=fake_boto)

    messages = await client.receive_messages(
        queue_url="http://localhost:4566/queue",
        max_number=10,
        wait_time_seconds=20,
    )

    assert len(messages) == 1
    assert messages[0]["MessageId"] == "msg-1"
    assert fake_boto.received_calls[0]["WaitTimeSeconds"] == 20
    assert fake_boto.received_calls[0]["MaxNumberOfMessages"] == 10


async def test_sqs_client_delete_messages_batch_chunks_at_10() -> None:
    fake_boto = _FakeBotoSqs()
    client = BotoSqsClient(boto_client=fake_boto)

    handles = [f"handle-{i}" for i in range(25)]
    await client.delete_messages_batch("http://localhost:4566/queue", handles)

    # 25 handles devem gerar 3 requisições de delete (10, 10, 5)
    assert len(fake_boto.deleted_batches) == 3
    assert len(fake_boto.deleted_batches[0]["Entries"]) == 10
    assert len(fake_boto.deleted_batches[1]["Entries"]) == 10
    assert len(fake_boto.deleted_batches[2]["Entries"]) == 5


async def test_sqs_client_change_visibility() -> None:
    fake_boto = _FakeBotoSqs()
    client = BotoSqsClient(boto_client=fake_boto)

    await client.change_message_visibility("http://localhost:4566/queue", "rh-abc", 0)

    assert len(fake_boto.visibility_changes) == 1
    assert fake_boto.visibility_changes[0]["ReceiptHandle"] == "rh-abc"
    assert fake_boto.visibility_changes[0]["VisibilityTimeout"] == 0


async def test_sqs_client_send_message_to_dlq() -> None:
    fake_boto = _FakeBotoSqs()
    client = BotoSqsClient(boto_client=fake_boto)

    msg_id = await client.send_message(
        "http://localhost:4566/dlq",
        '{"corrupt": true}',
        message_attributes={"x-error": {"DataType": "String", "StringValue": "bad"}},
    )

    assert msg_id == "dlq-msg-1"
    assert fake_boto.sent_messages[0]["QueueUrl"] == "http://localhost:4566/dlq"
    assert fake_boto.sent_messages[0]["MessageAttributes"] == {
        "x-error": {"DataType": "String", "StringValue": "bad"}
    }


async def test_sqs_client_propagates_client_errors() -> None:
    fake_boto = _FakeBotoSqs(should_fail=True)
    client = BotoSqsClient(boto_client=fake_boto)

    with pytest.raises(ClientError):
        await client.receive_messages("http://localhost:4566/queue")

    with pytest.raises(ClientError):
        await client.delete_messages_batch("http://localhost:4566/queue", ["rh-1"])

    with pytest.raises(ClientError):
        await client.send_message("http://localhost:4566/queue", "body")
