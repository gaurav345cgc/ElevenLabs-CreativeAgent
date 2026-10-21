"""Phase 10 — review escalation and idempotency key tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from models.enums import AudioChunkStatus, AudioJobStatus
from models.records import TranscriptAudioChunkRecord, TranscriptAudioJobRecord
from tts_pipeline.generator.chunk_generation import (
    ChunkGenerationError,
    is_permanent_generation_error,
    is_transient_generation_error,
)
from tts_pipeline.generator.elevenlabs_client import ElevenLabsApiError
from tts_pipeline.intake.chunk_idempotency import build_chunk_idempotency_key
from tts_pipeline.finalizer import FinalAudioMergeError
from tts_pipeline.orchestrator.errors import WorkflowValidationError
from tts_pipeline.orchestrator.review_escalation import (
    DEFAULT_MAX_WORKFLOW_RETRIES,
    chunk_failure_requires_review,
    should_escalate_job_to_review,
)


def _job(**overrides) -> TranscriptAudioJobRecord:
    now = datetime.now(UTC)
    base = {
        "id": uuid4(),
        "transcript_id": uuid4(),
        "transcript_version_id": uuid4(),
        "tenant_id": uuid4(),
        "idempotency_key": "test",
        "voice_profile_code": "drew_primary",
        "voice_id": "voice",
        "model_id": "eleven_multilingual_v2",
        "output_format": "mp3_44100_128",
        "status": AudioJobStatus.GENERATING,
        "retry_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    base.update(overrides)
    return TranscriptAudioJobRecord(**base)


def _chunk(job: TranscriptAudioJobRecord, index: int, **overrides) -> TranscriptAudioChunkRecord:
    now = datetime.now(UTC)
    data = {
        "id": uuid4(),
        "audio_job_id": job.id,
        "transcript_id": job.transcript_id,
        "transcript_version_id": job.transcript_version_id,
        "chunk_index": index,
        "status": AudioChunkStatus.FAILED,
        "source_text": "text",
        "output_format": job.output_format,
        "mime_type": "audio/mpeg",
        "character_count": 4,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return TranscriptAudioChunkRecord(**data)


def test_build_chunk_idempotency_key_is_stable() -> None:
    job_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    assert build_chunk_idempotency_key(audio_job_id=job_id, chunk_index=3) == (
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee:3:tts-chunk-v1"
    )


def test_is_permanent_generation_error() -> None:
    assert is_permanent_generation_error(ElevenLabsApiError("quota", status_code=402)) is True
    assert is_permanent_generation_error(ElevenLabsApiError("busy", status_code=503)) is False
    assert is_permanent_generation_error(ChunkGenerationError("invalid job")) is True
    assert is_transient_generation_error(ElevenLabsApiError("busy", status_code=503)) is True


def test_chunk_failure_requires_review_for_permanent_provider_error() -> None:
    job = _job()
    chunk = _chunk(
        job,
        0,
        error_code="ElevenLabsApiError",
        metadata_json={"provider_status_code": 402},
    )
    assert chunk_failure_requires_review(chunk) is True


def test_chunk_failure_does_not_require_review_for_transient_provider_error() -> None:
    job = _job()
    chunk = _chunk(
        job,
        0,
        error_code="ElevenLabsApiError",
        metadata_json={"provider_status_code": 503},
    )
    assert chunk_failure_requires_review(chunk) is False


def test_should_escalate_on_validation_error() -> None:
    job = _job()
    assert should_escalate_job_to_review(job, [], error=WorkflowValidationError("bad input")) is True


def test_should_escalate_after_max_workflow_retries() -> None:
    job = _job(retry_count=DEFAULT_MAX_WORKFLOW_RETRIES)
    assert should_escalate_job_to_review(job, []) is True


def test_should_not_escalate_transient_partial_failure() -> None:
    job = _job()
    chunk = _chunk(
        job,
        0,
        error_code="ElevenLabsApiError",
        metadata_json={"provider_status_code": 503},
    )
    assert should_escalate_job_to_review(job, [chunk]) is False


def test_should_not_escalate_mix_disk_error_before_retry_limit() -> None:
    job = _job(retry_count=1)
    err = FinalAudioMergeError(
        "background mix failed: ffmpeg background mix failed: No space left on device"
    )
    assert should_escalate_job_to_review(job, [], error=err) is False
