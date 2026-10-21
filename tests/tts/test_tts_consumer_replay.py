"""SQS consumer replay entry state."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from models.enums import AudioJobStatus
from models.records import TranscriptAudioJobRecord
from tts_pipeline.consumer_service import resolve_workflow_start_state
from tts_pipeline.orchestrator.workflow import WorkflowState


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
        "status": AudioJobStatus.PARTIALLY_FAILED,
        "retry_count": 3,
        "created_at": now,
        "updated_at": now,
    }
    base.update(overrides)
    return TranscriptAudioJobRecord(**base)


def test_resolve_skips_completed() -> None:
    job = _job(status=AudioJobStatus.COMPLETED)
    assert resolve_workflow_start_state(job, has_final_asset=True, has_master_asset=True) is None


def test_resolve_mix_only_when_final_without_master() -> None:
    job = _job(status=AudioJobStatus.REVIEW_REQUIRED)
    assert (
        resolve_workflow_start_state(job, has_final_asset=True, has_master_asset=False)
        is WorkflowState.MIX_BACKGROUND
    )


def test_resolve_full_pipeline_when_no_final() -> None:
    job = _job(status=AudioJobStatus.READY)
    assert (
        resolve_workflow_start_state(job, has_final_asset=False, has_master_asset=False)
        is WorkflowState.LOAD_ENHANCED_TRANSCRIPT
    )
