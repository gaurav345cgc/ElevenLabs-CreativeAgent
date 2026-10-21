"""Synthesize one chunk and store it in S3."""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import UUID

from observability.tts import log_tts_provider_synthesis, log_tts_storage_failure
from tts_pipeline.generator.elevenlabs_client import (
    ElevenLabsClient,
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
)
from tts_pipeline.persistence.s3_audio import StoredAudioObject, write_audio_object
from tts_pipeline.persistence.s3_keys import chunk_object_key


@dataclass(frozen=True, slots=True)
class StoredChunkSynthesis:
    result: SpeechSynthesisResult
    stored: StoredAudioObject


def synthesize_and_store_chunk(
    client: ElevenLabsClient,
    request: SpeechSynthesisRequest,
    *,
    tenant_id: UUID | str,
    transcript_id: UUID | str,
    audio_job_id: UUID | str,
    chunk_index: int,
    bucket: str | None = None,
    s3_client=None,
) -> StoredChunkSynthesis:
    """Create speech for one chunk and write mp3 bytes to S3."""
    started = time.perf_counter()
    result = client.synthesize(request)
    latency_ms = int((time.perf_counter() - started) * 1000)
    log_tts_provider_synthesis(
        audio_job_id=str(audio_job_id),
        transcript_id=str(transcript_id),
        chunk_index=chunk_index,
        request_id=result.request_id,
        voice_id=request.voice_id,
        model_id=request.model_id,
        latency_ms=latency_ms,
        byte_size=result.byte_size,
    )
    object_key = chunk_object_key(tenant_id, transcript_id, audio_job_id, chunk_index)
    try:
        stored = write_audio_object(
            bucket=bucket,
            object_key=object_key,
            audio_bytes=result.audio_bytes,
            checksum_sha256=result.checksum_sha256,
            mime_type=result.mime_type,
            metadata={
                "request-id": result.request_id or "",
                "output-format": result.output_format,
            },
            s3_client=s3_client,
        )
    except Exception as exc:
        log_tts_storage_failure(
            audio_job_id=str(audio_job_id),
            transcript_id=str(transcript_id),
            chunk_index=chunk_index,
            object_key=object_key,
            error_type=type(exc).__name__,
            error_message=str(exc)[:500],
        )
        raise
    return StoredChunkSynthesis(result=result, stored=stored)
