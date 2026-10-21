"""Consume enhancement jobs from SQS with idempotency and validation."""

from __future__ import annotations

from db.repositories import TranscriptRepository
from db.session import build_session_factory, session_scope
from models.messages import EnhancementJobMessage
from observability.logging import log_enhancer_event
from queues.consumer import EnhancementHandoffHandler, HandoffOutcome
from queues.idempotency import should_skip_duplicate_enhancement, validate_enhancement_handoff
from queues.processor import EnhancementJobProcessor
from tts_enhancer.processor import EnhancementJobProcessorImpl


class EnhancementConsumerService(EnhancementHandoffHandler):
    """Validate SQS handoff, skip duplicates, delegate to Agent 2 processor."""

    def __init__(
        self,
        *,
        repository: TranscriptRepository | None = None,
        processor: EnhancementJobProcessor | None = None,
        database_url: str | None = None,
    ) -> None:
        if repository is not None:
            self._repository = repository
        else:
            self._repository = TranscriptRepository(build_session_factory(database_url))
        self._processor = processor or EnhancementJobProcessorImpl()

    def handle(self, message: EnhancementJobMessage) -> str:
        correlation_id = message.correlation_id
        log_enhancer_event(
            "enhancement_handoff_received",
            correlation_id=correlation_id,
            transcript_id=message.transcript_id,
            tenant_id=message.tenant_id,
            raw_version_id=message.raw_version_id,
            idempotency_key=message.idempotency_key,
            requested_output_mode=message.requested_output_mode.value,
        )

        with session_scope(self._repository._session_factory) as session:
            if should_skip_duplicate_enhancement(self._repository, session, message):
                self._repository.record_job_event(
                    session,
                    message.transcript_id,
                    "enhancement_duplicate_skipped",
                    event_payload={
                        "idempotency_key": message.idempotency_key,
                        "raw_version_id": str(message.raw_version_id),
                    },
                    correlation_id=correlation_id,
                )
                log_enhancer_event(
                    "enhancement_duplicate_skipped",
                    correlation_id=correlation_id,
                    transcript_id=message.transcript_id,
                    idempotency_key=message.idempotency_key,
                )
                return HandoffOutcome.SKIPPED_DUPLICATE

            handoff = validate_enhancement_handoff(self._repository, session, message)
            self._repository.record_job_event(
                session,
                message.transcript_id,
                "enhancement_handoff_validated",
                event_payload={
                    "raw_version_id": str(message.raw_version_id),
                    "status": handoff.status.value,
                },
                correlation_id=correlation_id,
            )

        self._processor.process(message)
        log_enhancer_event(
            "enhancement_handoff_processed",
            correlation_id=correlation_id,
            transcript_id=message.transcript_id,
            raw_version_id=message.raw_version_id,
        )
        return HandoffOutcome.PROCESSED


def build_enhancement_consumer_for_tests(
    *,
    processor: EnhancementJobProcessor | None = None,
    database_url: str | None = None,
) -> EnhancementConsumerService:
    return EnhancementConsumerService(processor=processor, database_url=database_url)
