"""Chunk-level idempotency keys for TTS generation."""

from __future__ import annotations

from uuid import UUID

TTS_CHUNK_IDEMPOTENCY_VERSION = "tts-chunk-v1"


def build_chunk_idempotency_key(
    *,
    audio_job_id: UUID,
    chunk_index: int,
    version: str = TTS_CHUNK_IDEMPOTENCY_VERSION,
) -> str:
    """Stable identity for one chunk artifact within a job."""
    return f"{audio_job_id}:{chunk_index}:{version}"
