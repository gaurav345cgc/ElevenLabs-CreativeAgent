"""Publish TTS audio workflow jobs to SQS."""

from __future__ import annotations

import json
import os
from typing import Protocol

from models.messages import TtsAudioJobMessage
from observability.logging import log_queue_event


class TtsQueuePublisher(Protocol):
    def publish(self, message: TtsAudioJobMessage) -> str: ...


class SqsTtsPublisher:
    """Send identifier-only TTS workflow messages to SQS."""

    def __init__(
        self,
        *,
        queue_url: str | None = None,
        sqs_client=None,
        region_name: str | None = None,
    ) -> None:
        self._queue_url = queue_url or os.environ.get("CREATIVE_AGENT_TTS_QUEUE_URL")
        if not self._queue_url:
            raise ValueError("CREATIVE_AGENT_TTS_QUEUE_URL is not configured")
        if sqs_client is not None:
            self._client = sqs_client
        else:
            import boto3

            self._client = boto3.client(
                "sqs",
                region_name=region_name or os.environ.get("CREATIVE_AGENT_AWS_REGION", "us-east-1"),
            )

    def publish(self, message: TtsAudioJobMessage) -> str:
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
            "tts job published",
            event_type="tts_published",
            queue_name="tts",
            message_id=message_id,
            audio_job_id=str(message.audio_job_id),
            correlation_id=message.correlation_id,
        )
        return message_id


class InMemoryTtsPublisher:
    """Test double that records published messages."""

    def __init__(self) -> None:
        self.messages: list[TtsAudioJobMessage] = []

    def publish(self, message: TtsAudioJobMessage) -> str:
        self.messages.append(message)
        return f"in-memory-{len(self.messages)}"


def load_tts_message_from_sqs_body(body: str) -> TtsAudioJobMessage:
    """Parse an SQS message body back into the contract (for tests/consumers)."""
    return TtsAudioJobMessage.model_validate(json.loads(body))
