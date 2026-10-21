"""Parse SQS Lambda events and run TTS workflow handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from models.messages import TtsAudioJobMessage
from observability.tts import log_tts_workflow_failed
from queues.tts_publisher import load_tts_message_from_sqs_body


class TtsHandoffOutcome:
    PROCESSED = "processed"
    SKIPPED_DUPLICATE = "skipped_duplicate"


class TtsWorkflowHandoffHandler(Protocol):
    def handle(self, message: TtsAudioJobMessage) -> str: ...


@dataclass(frozen=True, slots=True)
class TtsSqsRecord:
    message_id: str
    receipt_handle: str
    body: str
    message: TtsAudioJobMessage
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class TtsSqsBatchResult:
    processed: int
    skipped: int
    failed_message_ids: tuple[str, ...]

    def to_lambda_response(self) -> dict[str, Any]:
        return {
            "batchItemFailures": [
                {"itemIdentifier": message_id} for message_id in self.failed_message_ids
            ]
        }


def parse_tts_sqs_lambda_event(event: dict[str, Any]) -> list[TtsSqsRecord]:
    records = event.get("Records") or []
    parsed: list[TtsSqsRecord] = []
    for record in records:
        body = record.get("body") or ""
        message = load_tts_message_from_sqs_body(body)
        attributes = record.get("messageAttributes") or {}
        correlation_attr = attributes.get("correlation_id") or {}
        correlation_id = message.correlation_id or correlation_attr.get("stringValue")
        parsed.append(
            TtsSqsRecord(
                message_id=str(record["messageId"]),
                receipt_handle=str(record.get("receiptHandle", "")),
                body=body,
                message=message,
                correlation_id=correlation_id,
            )
        )
    return parsed


def process_tts_sqs_batch(
    records: list[TtsSqsRecord],
    handler: TtsWorkflowHandoffHandler,
) -> TtsSqsBatchResult:
    processed = 0
    skipped = 0
    failed: list[str] = []

    for record in records:
        try:
            outcome = handler.handle(record.message)
            if outcome == TtsHandoffOutcome.SKIPPED_DUPLICATE:
                skipped += 1
            else:
                processed += 1
        except Exception as exc:
            log_tts_workflow_failed(
                correlation_id=record.correlation_id,
                audio_job_id=str(record.message.audio_job_id),
                error=str(exc),
                sqs_message_id=record.message_id,
            )
            failed.append(record.message_id)

    return TtsSqsBatchResult(
        processed=processed,
        skipped=skipped,
        failed_message_ids=tuple(failed),
    )
