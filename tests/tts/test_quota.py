"""Tests for ElevenLabs quota preflight and error parsing."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from models.enums import AudioChunkStatus, AudioJobStatus
from models.records import TranscriptAudioChunkRecord, TranscriptAudioJobRecord
from tts_pipeline.generator.chunk_generation import ChunkGenerationError, generate_chunks_sequentially
from tts_pipeline.generator.elevenlabs_client import ElevenLabsApiError, ElevenLabsSubscriptionSnapshot
from tts_pipeline.generator.quota import (
    QuotaExceededError,
    assert_sufficient_credits_for_pending_chunks,
    estimate_credits_for_chunks,
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
        "status": AudioJobStatus.READY,
        "seed": 1337,
        "enable_logging": True,
        "created_at": now,
        "updated_at": now,
    }
    base.update(overrides)
    return TranscriptAudioJobRecord(**base)


def _chunk(job: TranscriptAudioJobRecord, index: int, text: str, **overrides) -> TranscriptAudioChunkRecord:
    now = datetime.now(UTC)
    data = {
        "id": uuid4(),
        "audio_job_id": job.id,
        "transcript_id": job.transcript_id,
        "transcript_version_id": job.transcript_version_id,
        "chunk_index": index,
        "status": AudioChunkStatus.PLANNED,
        "source_text": text,
        "output_format": job.output_format,
        "mime_type": "audio/mpeg",
        "character_count": len(text),
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return TranscriptAudioChunkRecord(**data)


def test_elevenlabs_api_error_parses_quota_fields() -> None:
    exc = ElevenLabsApiError(
        'ElevenLabs create speech failed (401): {"detail":{"code":"quota_exceeded",'
        '"message":"You have 194 credits remaining, while 368 credits are required"}}',
        status_code=401,
    )
    assert exc.is_quota_exceeded is True
    assert exc.provider_error_code == "quota_exceeded"
    assert exc.credits_remaining == 194
    assert exc.credits_required == 368


def test_assert_sufficient_credits_raises_when_pending_exceeds_balance() -> None:
    job = _job()
    chunks = [_chunk(job, index, "x" * 400) for index in range(3)]

    class FakeClient:
        def get_subscription(self) -> ElevenLabsSubscriptionSnapshot:
            return ElevenLabsSubscriptionSnapshot(character_count=9806, character_limit=10000, tier="starter")

    with pytest.raises(QuotaExceededError, match="only 194 credits remain"):
        assert_sufficient_credits_for_pending_chunks(FakeClient(), job, chunks)

    assert estimate_credits_for_chunks(chunks) == 1200


def test_generate_chunks_preflight_fails_before_provider_calls(monkeypatch) -> None:
    job = _job()
    chunks = [_chunk(job, 0, "hello world")]

    class FakeRepo:
        def mark_job_generating(self, *args, **kwargs):
            return job

    class FakeClient:
        def get_subscription(self) -> ElevenLabsSubscriptionSnapshot:
            return ElevenLabsSubscriptionSnapshot(character_count=9999, character_limit=10000)

    called = {"synth": False}

    def _should_not_run(*args, **kwargs):
        called["synth"] = True
        raise AssertionError("synthesis should not run when preflight fails")

    monkeypatch.setattr(
        "tts_pipeline.generator.chunk_generation.generate_single_chunk",
        _should_not_run,
    )

    with pytest.raises(ChunkGenerationError, match="only 1 credits remain"):
        generate_chunks_sequentially(None, FakeRepo(), job, chunks, FakeClient())

    assert called["synth"] is False
