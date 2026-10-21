"""Phase 2 domain contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from models import (
    Agent1Output,
    CreateTranscriptRequest,
    EnhancementJobMessage,
    ErrorEnvelope,
    ErrorCode,
    SectionedScriptContent,
    ScriptSection,
    TaxonomyContext,
    build_enhancement_idempotency_key,
    build_example_pattern_plan,
    validate_pattern_plan,
)
from models.metadata import DurationEstimate, RawPatternMetadata
from models.records import TranscriptRecord, TranscriptVersionRecord
from models.enums import TranscriptStatus, VersionKind


def test_create_transcript_request_valid() -> None:
    req = CreateTranscriptRequest(
        tenant_id=uuid4(),
        content_type="guided_meditation",
        generation_code="millennial",
        wound_id="ml_02",
        stage_no=2,
        target_duration_minutes=12,
        pillar_code="p04",
        title_hint="Evening reset",
    )
    assert req.wound_id == "ml_02"
    assert req.requested_output_mode.value == "plain_paste"


def test_create_transcript_request_rejects_unknown_wound() -> None:
    with pytest.raises(ValidationError):
        CreateTranscriptRequest(
            tenant_id=uuid4(),
            content_type="guided_meditation",
            generation_code="millennial",
            wound_id="unknown_wound",
            stage_no=1,
            target_duration_minutes=10,
        )


def test_create_transcript_request_rejects_invalid_stage_for_wound() -> None:
    with pytest.raises(ValidationError):
        CreateTranscriptRequest(
            tenant_id=uuid4(),
            content_type="guided_meditation",
            generation_code="gen_z",
            wound_id="gz_01",
            stage_no=99,
            target_duration_minutes=10,
        )


def test_enhancement_job_message_idempotency_key() -> None:
    transcript_id = uuid4()
    raw_version_id = uuid4()
    tenant_id = uuid4()

    message = EnhancementJobMessage.from_ids(
        transcript_id=transcript_id,
        tenant_id=tenant_id,
        raw_version_id=raw_version_id,
    )
    expected = build_enhancement_idempotency_key(transcript_id, raw_version_id)
    assert message.idempotency_key == expected
    assert message.schema_version == "1.0"


def test_enhancement_job_message_rejects_wrong_idempotency_key() -> None:
    with pytest.raises(ValidationError):
        EnhancementJobMessage(
            transcript_id=uuid4(),
            tenant_id=uuid4(),
            raw_version_id=uuid4(),
            idempotency_key="wrong",
        )


def test_pattern_plan_validation() -> None:
    plan = build_example_pattern_plan()
    validate_pattern_plan(plan)
    assert len(plan.slots) == 6


def test_transcript_record_round_trip() -> None:
    now = datetime.now(UTC)
    record = TranscriptRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        content_type="guided_meditation",
        status=TranscriptStatus.PENDING_ENHANCEMENT,
        created_at=now,
        updated_at=now,
        generation_code="millennial",
        wound_id="ml_02",
        stage_no=2,
    )
    assert record.status == TranscriptStatus.PENDING_ENHANCEMENT


def test_transcript_version_record() -> None:
    now = datetime.now(UTC)
    record = TranscriptVersionRecord(
        id=uuid4(),
        transcript_id=uuid4(),
        version_kind=VersionKind.RAW_PATTERN,
        content_text="Hello.",
        created_by_agent="pattern_transcript_composer",
        metadata_json={"schema_version": "1.0"},
        created_at=now,
    )
    assert record.version_kind == VersionKind.RAW_PATTERN


def test_agent1_output_shape() -> None:
    taxonomy = TaxonomyContext(
        generation_code="millennial",
        wound_id="ml_02",
        stage_no=1,
        pillar_code="p04",
    )
    plan = build_example_pattern_plan()
    metadata = RawPatternMetadata(
        taxonomy=taxonomy,
        pattern_plan=plan,
        duration_estimate=DurationEstimate(seconds=600),
        title="Test",
    )
    sectioned = SectionedScriptContent(
        sections=[ScriptSection(slot="opening", text="Welcome.")]
    )
    output = Agent1Output(
        transcript_id=uuid4(),
        version_id=uuid4(),
        title="Test",
        transcript_text="Welcome.",
        sectioned_script=sectioned,
        pattern_plan=plan,
        taxonomy=taxonomy,
        duration_estimate=DurationEstimate(seconds=600),
        metadata=metadata,
    )
    assert output.status == TranscriptStatus.PENDING_ENHANCEMENT


def test_error_envelope() -> None:
    err = ErrorEnvelope(
        error_code=ErrorCode.VALIDATION_ERROR,
        message="Invalid brief",
        details={"field": "wound_id"},
        correlation_id="corr-1",
    )
    assert err.error_code == ErrorCode.VALIDATION_ERROR
