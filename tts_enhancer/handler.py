"""AWS Lambda entrypoint for Agent 2 — SQS consumer."""

from __future__ import annotations

from typing import Any

from queues.consumer import parse_sqs_lambda_event, process_sqs_batch
from tts_enhancer.consumer_service import EnhancementConsumerService


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """SQS-triggered Lambda 2 handler with partial batch failure reporting."""
    records = parse_sqs_lambda_event(event)
    if not records:
        return {"batchItemFailures": []}

    consumer = EnhancementConsumerService()
    result = process_sqs_batch(records, consumer)
    return result.to_lambda_response()
