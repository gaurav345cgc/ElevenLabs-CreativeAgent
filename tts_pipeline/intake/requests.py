"""TTS job intake request and result types."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from models.records import TranscriptAudioJobRecord, TranscriptRecord, TranscriptVersionRecord
from tts_pipeline.voice_policy import DEFAULT_VOICE_PROFILE_CODE


@dataclass(frozen=True, slots=True)
class CreateAudioJobRequest:
    tenant_id: UUID
    transcript_id: UUID
    transcript_version_id: UUID
    voice_profile_code: str = DEFAULT_VOICE_PROFILE_CODE
    idempotency_key: str | None = None
    seed_override: int | None = None
    correlation_id: str | None = None
    audio_job_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CreateAudioJobResult:
    audio_job: TranscriptAudioJobRecord
    transcript: TranscriptRecord
    transcript_version: TranscriptVersionRecord
    created: bool
