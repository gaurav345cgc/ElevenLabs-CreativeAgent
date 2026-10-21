"""Publish enhancement jobs to SQS."""

from __future__ import annotations

import json
import os
from typing import Protocol

from models.messages import EnhancementJobMessage
from observability.logging import log_queue_event


class EnhancementQueuePublisher(Protocol):
    def publish(self, message: EnhancementJobMessage) -> str: ...


class SqsEnhancementPublisher:
    """Send identifier-only enhancement messages to SQS."""

    def __init__(
        self,
        *,
        queue_url: str | None = None,
        sqs_client=None,
        region_name: str | None = None,
    ) -> None:
        self._queue_url = queue_url or os.environ.get("CREATIVE_AGENT_ENHANCEMENT_QUEUE_URL")
        if not self._queue_url:
            raise ValueError("CREATIVE_AGENT_ENHANCEMENT_QUEUE_URL is not configured")
        if sqs_client is not None:
            self._client = sqs_client
        else:
            import boto3

            self._client = boto3.client(
                "sqs",
                region_name=region_name or os.environ.get("CREATIVE_AGENT_AWS_REGION", "us-east-1"),
            )

    def publish(self, message: EnhancementJobMessage) -> str:
        attributes: dict[str, dict[str, str]] = {
            "idempotency_key": {
                "DataType": "String",
                "StringValue": message.idempotency_key,
            },
        }
        if message.correlation_id:
            attributes["correlation_id"] = {
                "DataType": "String",
                "StringValue": message.correlation_id,
            }
        response = self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=message.model_dump_json(),
            MessageAttributes=attributes,
        )
        message_id = response["MessageId"]
        log_queue_event(
            "enhancement job published",
            event_type="enhancement_published",
            queue_name="enhancement",
            message_id=message_id,
            transcript_id=str(message.transcript_id),
            correlation_id=message.correlation_id,
        )
        return message_id


class InMemoryEnhancementPublisher:
    """Test double that records published messages."""

    def __init__(self) -> None:
        self.messages: list[EnhancementJobMessage] = []

    def publish(self, message: EnhancementJobMessage) -> str:
        self.messages.append(message)
        return f"in-memory-{len(self.messages)}"


def load_message_from_sqs_body(body: str) -> EnhancementJobMessage:
    """Parse an SQS message body back into the contract (for tests/consumers)."""
    return EnhancementJobMessage.model_validate(json.loads(body))
