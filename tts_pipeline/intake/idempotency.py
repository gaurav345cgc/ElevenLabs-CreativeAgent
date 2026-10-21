"""Job-level idempotency keys for TTS intake."""

from __future__ import annotations

from uuid import UUID

TTS_JOB_IDEMPOTENCY_VERSION = "tts-v3-pause-v7"


def build_audio_job_idempotency_key(
    *,
    transcript_id: UUID,
    transcript_version_id: UUID,
    voice_profile_code: str,
    version: str = TTS_JOB_IDEMPOTENCY_VERSION,
) -> str:
    return f"{transcript_id}:{transcript_version_id}:{voice_profile_code}:{version}"
