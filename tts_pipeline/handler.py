"""AWS Lambda entrypoint for TTS plane — SQS consumer."""

from __future__ import annotations

from typing import Any

from queues.tts_consumer import parse_tts_sqs_lambda_event, process_tts_sqs_batch
from tts_pipeline.consumer_service import TtsWorkflowConsumerService


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """SQS-triggered TTS worker: run orchestrator workflow per audio job."""
    records = parse_tts_sqs_lambda_event(event)
    if not records:
        return {"batchItemFailures": []}

    consumer = TtsWorkflowConsumerService()
    result = process_tts_sqs_batch(records, consumer)
    return result.to_lambda_response()
