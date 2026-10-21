"""Phase 7 — queue handoff and SQS consumer tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from db.engine import get_database_url
from db.repositories import InsertTranscriptVersionInput, TranscriptRepository
from db.session import build_session_factory, session_scope
from models.enums import EnhancementMode, TranscriptStatus, VersionKind
from models.messages import EnhancementJobMessage
from queues.consumer import (
    HandoffOutcome,
    build_sample_sqs_lambda_event,
    parse_sqs_lambda_event,
    process_sqs_batch,
)
from queues.idempotency import should_skip_duplicate_enhancement, validate_enhancement_handoff
from queues.processor import NotConfiguredEnhancementProcessor
from queues.publisher import load_message_from_sqs_body
from tests.test_transcript_repository import requires_postgres
from transcript_composer.service import build_agent1_service_for_tests
from tts_enhancer.consumer_service import build_enhancement_consumer_for_tests
from tts_enhancer.handler import handler as enhancer_handler
from models.requests import CreateTranscriptRequest


def _sample_request(**overrides) -> CreateTranscriptRequest:
    payload = {
        "tenant_id": uuid4(),
        "content_type": "guided_meditation",
        "generation_code": "millennial",
        "wound_id": "ml_02",
        "stage_no": 2,
        "target_duration_minutes": 10,
        "pillar_code": "p04",
    }
    payload.update(overrides)
    return CreateTranscriptRequest(**payload)


def test_enhancement_message_is_identifier_only() -> None:
    message = EnhancementJobMessage.from_ids(
        transcript_id=uuid4(),
        tenant_id=uuid4(),
        raw_version_id=uuid4(),
        correlation_id="corr-123",
    )
    payload = message.model_dump()
    assert "content_text" not in payload
    assert "transcript_text" not in payload
    assert set(payload.keys()) >= {
        "schema_version",
        "transcript_id",
        "tenant_id",
        "raw_version_id",
        "requested_output_mode",
        "voice_model",
        "idempotency_key",
    }


def test_parse_sqs_lambda_event_round_trip() -> None:
    message = EnhancementJobMessage.from_ids(
        transcript_id=uuid4(),
        tenant_id=uuid4(),
        raw_version_id=uuid4(),
        correlation_id="trace-abc",
    )
    event = build_sample_sqs_lambda_event(message, message_id="sqs-42")
    records = parse_sqs_lambda_event(event)
    assert len(records) == 1
    record = records[0]
    assert record.message_id == "sqs-42"
    assert record.message.transcript_id == message.transcript_id
    assert record.correlation_id == "trace-abc"
    assert load_message_from_sqs_body(record.body).idempotency_key == message.idempotency_key


def test_process_sqs_batch_reports_partial_failures() -> None:
    good = EnhancementJobMessage.from_ids(
        transcript_id=uuid4(),
        tenant_id=uuid4(),
        raw_version_id=uuid4(),
    )
    bad = EnhancementJobMessage.from_ids(
        transcript_id=uuid4(),
        tenant_id=uuid4(),
        raw_version_id=uuid4(),
    )
    event = {
        "Records": [
            build_sample_sqs_lambda_event(good, message_id="ok")["Records"][0],
            build_sample_sqs_lambda_event(bad, message_id="fail")["Records"][0],
        ]
    }
    records = parse_sqs_lambda_event(event)

    class FlakyProcessor:
        def process(self, message: EnhancementJobMessage) -> None:
            if message.transcript_id == bad.transcript_id:
                raise RuntimeError("transient failure")

    class FlakyConsumer:
        def __init__(self) -> None:
            self._inner = FlakyProcessor()

        def handle(self, message: EnhancementJobMessage) -> str:
            self._inner.process(message)
            return HandoffOutcome.PROCESSED

    result = process_sqs_batch(records, FlakyConsumer())
    assert result.processed == 1
    assert result.failed_message_ids == ("fail",)
    assert result.to_lambda_response() == {"batchItemFailures": [{"itemIdentifier": "fail"}]}


def test_not_configured_processor_raises_for_retry() -> None:
    message = EnhancementJobMessage.from_ids(
        transcript_id=uuid4(),
        tenant_id=uuid4(),
        raw_version_id=uuid4(),
    )
    with pytest.raises(RuntimeError, match="Phase 8"):
        NotConfiguredEnhancementProcessor().process(message)


@requires_postgres
def test_agent1_message_validates_against_database() -> None:
    service, publisher = build_agent1_service_for_tests(database_url=get_database_url())
    request = _sample_request()
    result = service.run(request)
    message = publisher.messages[0]

    repo = TranscriptRepository(build_session_factory())
    with session_scope(repo._session_factory) as session:
        handoff = validate_enhancement_handoff(repo, session, message)
        assert handoff.transcript_id == result.output.transcript_id
        assert handoff.raw_version_id == result.output.version_id
        assert handoff.status == TranscriptStatus.PENDING_ENHANCEMENT
        assert should_skip_duplicate_enhancement(repo, session, message) is False


@requires_postgres
def test_duplicate_enhancement_delivery_is_skipped() -> None:
    service, publisher = build_agent1_service_for_tests(database_url=get_database_url())
    request = _sample_request()
    result = service.run(request)
    message = publisher.messages[0]

    repo = TranscriptRepository(build_session_factory())
    with session_scope(repo._session_factory) as session:
        repo.insert_transcript_version(
            session,
            InsertTranscriptVersionInput(
                transcript_id=result.output.transcript_id,
                version_kind=VersionKind.ELEVENLABS_ENHANCED,
                content_text="Already enhanced.",
                created_by_agent="elevenlabs_script_doctor",
                metadata_json={},
                source_version_id=result.output.version_id,
                enhancement_mode=EnhancementMode.PLAIN_PASTE,
            ),
        )

    consumer = build_enhancement_consumer_for_tests(database_url=get_database_url())
    outcome = consumer.handle(message)
    assert outcome == HandoffOutcome.SKIPPED_DUPLICATE


@requires_postgres
def test_handler_returns_batch_failure_when_processor_not_configured() -> None:
    service, publisher = build_agent1_service_for_tests(database_url=get_database_url())
    service.run(_sample_request())
    message = publisher.messages[0]
    event = build_sample_sqs_lambda_event(message, message_id="retry-me")

    import importlib

    handler_module = importlib.import_module("tts_enhancer.handler")
    consumer = build_enhancement_consumer_for_tests(
        database_url=get_database_url(),
        processor=NotConfiguredEnhancementProcessor(),
    )
    original_service = handler_module.EnhancementConsumerService
    handler_module.EnhancementConsumerService = lambda *args, **kwargs: consumer

    try:
        response = enhancer_handler(event, None)
    finally:
        handler_module.EnhancementConsumerService = original_service

    assert response == {"batchItemFailures": [{"itemIdentifier": "retry-me"}]}
