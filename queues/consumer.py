"""Parse SQS Lambda events and run enhancement handoff handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from models.messages import EnhancementJobMessage
from observability.logging import log_enhancer_event
from queues.publisher import load_message_from_sqs_body


class HandoffOutcome:
    PROCESSED = "processed"
    SKIPPED_DUPLICATE = "skipped_duplicate"


class EnhancementHandoffHandler(Protocol):
    def handle(self, message: EnhancementJobMessage) -> str: ...


@dataclass(frozen=True, slots=True)
class EnhancementSqsRecord:
    message_id: str
    receipt_handle: str
    body: str
    message: EnhancementJobMessage
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class SqsBatchResult:
    processed: int
    skipped: int
    failed_message_ids: tuple[str, ...]

    def to_lambda_response(self) -> dict[str, Any]:
        """Partial batch failure response for SQS-triggered Lambda."""
        return {
            "batchItemFailures": [
                {"itemIdentifier": message_id} for message_id in self.failed_message_ids
            ]
        }


def parse_sqs_lambda_event(event: dict[str, Any]) -> list[EnhancementSqsRecord]:
    """Parse an AWS Lambda SQS event into validated enhancement job records."""
    records = event.get("Records") or []
    parsed: list[EnhancementSqsRecord] = []
    for record in records:
        body = record.get("body") or ""
        message = load_message_from_sqs_body(body)
        attributes = record.get("messageAttributes") or {}
        correlation_attr = attributes.get("correlation_id") or {}
        correlation_id = message.correlation_id or correlation_attr.get("stringValue")
        parsed.append(
            EnhancementSqsRecord(
                message_id=str(record["messageId"]),
                receipt_handle=str(record.get("receiptHandle", "")),
                body=body,
                message=message,
                correlation_id=correlation_id,
            )
        )
    return parsed


def process_sqs_batch(
    records: list[EnhancementSqsRecord],
    handler: EnhancementHandoffHandler,
) -> SqsBatchResult:
    """Invoke the handler per record; collect per-message failures for SQS retry."""
    processed = 0
    skipped = 0
    failed: list[str] = []

    for record in records:
        try:
            outcome = handler.handle(record.message)
            if outcome == HandoffOutcome.SKIPPED_DUPLICATE:
                skipped += 1
            else:
                processed += 1
        except Exception as exc:
            log_enhancer_event(
                "enhancement_message_failed",
                level=40,
                correlation_id=record.correlation_id,
                sqs_message_id=record.message_id,
                transcript_id=record.message.transcript_id,
                raw_version_id=record.message.raw_version_id,
                error=str(exc),
            )
            failed.append(record.message_id)

    return SqsBatchResult(
        processed=processed,
        skipped=skipped,
        failed_message_ids=tuple(failed),
    )


def build_sample_sqs_lambda_event(
    message: EnhancementJobMessage,
    *,
    message_id: str = "msg-1",
) -> dict[str, Any]:
    """Build a minimal SQS Lambda event for tests."""
    attributes: dict[str, Any] = {}
    if message.correlation_id:
        attributes["correlation_id"] = {
            "stringValue": message.correlation_id,
            "dataType": "String",
        }
    return {
        "Records": [
            {
                "messageId": message_id,
                "receiptHandle": f"receipt-{message_id}",
                "body": message.model_dump_json(),
                "messageAttributes": attributes,
            }
        ]
    }
