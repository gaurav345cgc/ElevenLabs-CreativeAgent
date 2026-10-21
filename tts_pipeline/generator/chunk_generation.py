"""Phase 9 — chunk-by-chunk generation with retry and idempotency."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session

from db.repositories import AudioJobRepository
from models.enums import AudioChunkStatus, AudioJobStatus
from models.records import TranscriptAudioChunkRecord, TranscriptAudioJobRecord
from observability.tts import (
    log_tts_chunk_completed,
    log_tts_chunk_failed,
    log_tts_chunk_retry,
    log_tts_chunk_skipped,
    tts_context_from_chunk,
)
from tts_pipeline.generator.chunk_synthesis import StoredChunkSynthesis, synthesize_and_store_chunk
from tts_pipeline.generator.elevenlabs_client import ElevenLabsApiError, ElevenLabsClient, SpeechSynthesisRequest
from tts_pipeline.generator.quota import QuotaExceededError, assert_sufficient_credits_for_pending_chunks
from tts_pipeline.voice_policy import build_speech_synthesis_request

CHUNK_COMPLETED_EVENT = "CHUNK_COMPLETED"
CHUNK_FAILED_EVENT = "CHUNK_FAILED"
CHUNK_SKIPPED_EVENT = "CHUNK_SKIPPED"

DEFAULT_MAX_TRANSIENT_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 2.0

TRANSIENT_HTTP_STATUS = frozenset({408, 429, 500, 502, 503, 504})
PERMANENT_HTTP_STATUS = frozenset({400, 401, 402, 403, 404, 422})


class ChunkGenerationError(RuntimeError):
    """Chunk generation failed in a non-recoverable way."""


@dataclass(frozen=True, slots=True)
class ChunkGenerationRunResult:
    completed: int
    failed: int
    skipped: int


class AudioJobWriter(Protocol):
    def mark_job_generating(
        self, session: Session, audio_job_id, *, correlation_id: str | None = None
    ): ...

    def mark_chunk_generating(self, session: Session, chunk_id): ...

    def mark_chunk_completed(self, session: Session, chunk_id, **kwargs): ...

    def mark_chunk_failed(
        self, session: Session, chunk_id, *, error_code: str, error_message: str, metadata_json=None
    ): ...

    def increment_job_chunk_counters(
        self, session: Session, audio_job_id, *, completed_delta: int = 0, failed_delta: int = 0
    ): ...

    def record_audio_event(
        self, session: Session, audio_job_id, event_type: str, payload, *, correlation_id: str | None = None
    ): ...


def is_transient_generation_error(exc: BaseException) -> bool:
    if isinstance(exc, OSError):
        return True
    if isinstance(exc, ElevenLabsApiError):
        if exc.status_code is None:
            return False
        return exc.status_code in TRANSIENT_HTTP_STATUS
    return False


def is_permanent_generation_error(exc: BaseException) -> bool:
    """Non-retryable provider or validation failures — route to REVIEW_REQUIRED."""
    if isinstance(exc, ChunkGenerationError):
        return True
    if isinstance(exc, ElevenLabsApiError):
        if exc.status_code is None:
            return False
        if exc.status_code in TRANSIENT_HTTP_STATUS:
            return False
        if exc.status_code in PERMANENT_HTTP_STATUS:
            return True
        if 400 <= exc.status_code < 500:
            return True
    return False


def should_skip_chunk_generation(chunk: TranscriptAudioChunkRecord) -> bool:
    """Idempotent skip — reuse existing successful chunk artifact."""
    return chunk.status is AudioChunkStatus.COMPLETED and bool(chunk.output_object_key)


def build_chunk_synthesis_request(
    job: TranscriptAudioJobRecord,
    chunk: TranscriptAudioChunkRecord,
    all_chunks: list[TranscriptAudioChunkRecord],
    *,
    regeneration: bool = False,
) -> SpeechSynthesisRequest:
    if job.voice_profile_code is None:
        raise ChunkGenerationError(f"audio job {job.id} has no voice_profile_code")

    previous_request_ids: list[str] | None = None
    next_request_ids: list[str] | None = None
    if regeneration or chunk.status is AudioChunkStatus.FAILED:
        previous_request_ids, next_request_ids = _neighbor_request_ids(all_chunks, chunk.chunk_index)

    return build_speech_synthesis_request(
        job.voice_profile_code,
        chunk.source_text,
        previous_text=chunk.previous_text if not previous_request_ids else None,
        next_text=chunk.next_text if not next_request_ids else None,
        previous_request_ids=previous_request_ids,
        next_request_ids=next_request_ids,
        requested_seed=job.seed,
        enable_logging=job.enable_logging,
    )


def _neighbor_request_ids(
    chunks: list[TranscriptAudioChunkRecord],
    chunk_index: int,
) -> tuple[list[str] | None, list[str] | None]:
    by_index = {item.chunk_index: item for item in chunks}
    previous_request_ids: list[str] | None = None
    next_request_ids: list[str] | None = None

    previous = by_index.get(chunk_index - 1)
    if previous and previous.eleven_request_id:
        previous_request_ids = [previous.eleven_request_id]

    nxt = by_index.get(chunk_index + 1)
    if nxt and nxt.eleven_request_id:
        next_request_ids = [nxt.eleven_request_id]

    return previous_request_ids, next_request_ids


def synthesize_chunk_with_retry(
    client: ElevenLabsClient,
    request: SpeechSynthesisRequest,
    *,
    tenant_id,
    transcript_id,
    audio_job_id,
    chunk_index: int,
    max_attempts: int = DEFAULT_MAX_TRANSIENT_RETRIES,
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
) -> StoredChunkSynthesis:
    attempt = 0
    while True:
        attempt += 1
        try:
            return synthesize_and_store_chunk(
                client,
                request,
                tenant_id=tenant_id,
                transcript_id=transcript_id,
                audio_job_id=audio_job_id,
                chunk_index=chunk_index,
            )
        except Exception as exc:
            if attempt >= max_attempts or not is_transient_generation_error(exc):
                raise
            log_tts_chunk_retry(
                audio_job_id=str(audio_job_id),
                transcript_id=str(transcript_id),
                chunk_index=chunk_index,
                attempt=attempt,
                max_attempts=max_attempts,
                error_type=type(exc).__name__,
            )
            time.sleep(retry_backoff_seconds * attempt)


def generate_single_chunk(
    session: Session,
    repo: AudioJobWriter,
    job: TranscriptAudioJobRecord,
    chunk: TranscriptAudioChunkRecord,
    all_chunks: list[TranscriptAudioChunkRecord],
    client: ElevenLabsClient,
    *,
    correlation_id: str | None = None,
) -> str:
    """Generate one chunk. Returns event type: completed, skipped, or failed."""
    if should_skip_chunk_generation(chunk):
        log_tts_chunk_skipped(
            **tts_context_from_chunk(
                job,
                chunk,
                correlation_id=correlation_id,
                object_key=chunk.output_object_key,
                reason="already_completed",
            )
        )
        repo.record_audio_event(
            session,
            job.id,
            CHUNK_SKIPPED_EVENT,
            {
                "chunk_index": chunk.chunk_index,
                "chunk_id": str(chunk.id),
                "object_key": chunk.output_object_key,
                "reason": "already_completed",
            },
            correlation_id=correlation_id,
        )
        return "skipped"

    was_failed = chunk.status is AudioChunkStatus.FAILED
    regeneration = was_failed
    repo.mark_chunk_generating(session, chunk.id)
    request = build_chunk_synthesis_request(job, chunk, all_chunks, regeneration=regeneration)

    try:
        stored = synthesize_chunk_with_retry(
            client,
            request,
            tenant_id=job.tenant_id,
            transcript_id=job.transcript_id,
            audio_job_id=job.id,
            chunk_index=chunk.chunk_index,
        )
        repo.mark_chunk_completed(
            session,
            chunk.id,
            eleven_request_id=stored.result.request_id,
            output_object_key=stored.stored.object_key,
            checksum_sha256=stored.result.checksum_sha256,
            byte_size=stored.result.byte_size,
            response_headers_json=stored.result.response_headers,
            metadata_json={
                "continuity_mode": "request_ids" if regeneration else "text",
            },
        )
        repo.increment_job_chunk_counters(
            session,
            job.id,
            completed_delta=1,
            failed_delta=-1 if was_failed else 0,
        )
        log_tts_chunk_completed(
            **tts_context_from_chunk(
                job,
                chunk,
                correlation_id=correlation_id,
                object_key=stored.stored.object_key,
                byte_size=stored.result.byte_size,
                checksum_sha256=stored.result.checksum_sha256,
            )
        )
        repo.record_audio_event(
            session,
            job.id,
            CHUNK_COMPLETED_EVENT,
            {
                "chunk_index": chunk.chunk_index,
                "chunk_id": str(chunk.id),
                "request_id": stored.result.request_id,
                "object_key": stored.stored.object_key,
                "byte_size": stored.result.byte_size,
                "checksum_sha256": stored.result.checksum_sha256,
            },
            correlation_id=correlation_id,
        )
        return "completed"
    except Exception as exc:
        failure_metadata: dict[str, object] = {}
        if isinstance(exc, ElevenLabsApiError):
            if exc.status_code is not None:
                failure_metadata["provider_status_code"] = exc.status_code
            if exc.provider_error_code:
                failure_metadata["provider_error_code"] = exc.provider_error_code
            if exc.is_quota_exceeded:
                failure_metadata["provider_error_code"] = "quota_exceeded"
                if exc.credits_remaining is not None:
                    failure_metadata["credits_remaining"] = exc.credits_remaining
                if exc.credits_required is not None:
                    failure_metadata["credits_required"] = exc.credits_required

        if not was_failed:
            repo.mark_chunk_failed(
                session,
                chunk.id,
                error_code=type(exc).__name__,
                error_message=str(exc)[:500],
                metadata_json=failure_metadata or None,
            )
            repo.increment_job_chunk_counters(session, job.id, failed_delta=1)
        else:
            repo.mark_chunk_failed(
                session,
                chunk.id,
                error_code=type(exc).__name__,
                error_message=str(exc)[:500],
                metadata_json=failure_metadata or None,
            )

        log_tts_chunk_failed(
            **tts_context_from_chunk(
                job,
                chunk,
                correlation_id=correlation_id,
                error_code=type(exc).__name__,
                error_message=str(exc)[:500],
                transient=is_transient_generation_error(exc),
            )
        )
        repo.record_audio_event(
            session,
            job.id,
            CHUNK_FAILED_EVENT,
            {
                "chunk_index": chunk.chunk_index,
                "chunk_id": str(chunk.id),
                "error_code": type(exc).__name__,
                "error_message": str(exc)[:500],
                "transient": is_transient_generation_error(exc),
                **(
                    {"provider_error_code": failure_metadata.get("provider_error_code")}
                    if failure_metadata.get("provider_error_code")
                    else {}
                ),
            },
            correlation_id=correlation_id,
        )

        if isinstance(exc, ElevenLabsApiError) and exc.is_quota_exceeded:
            raise QuotaExceededError(
                str(exc),
                credits_remaining=exc.credits_remaining,
                credits_required=exc.credits_required,
            ) from exc
        return "failed"


def generate_chunks_sequentially(
    session: Session,
    repo: AudioJobRepository,
    job: TranscriptAudioJobRecord,
    chunks: list[TranscriptAudioChunkRecord],
    client: ElevenLabsClient,
    *,
    correlation_id: str | None = None,
) -> ChunkGenerationRunResult:
    """Synthesize each planned chunk in order without aborting the whole job on one failure."""
    if job.voice_profile_code is None:
        raise ChunkGenerationError(f"audio job {job.id} has no voice_profile_code")

    if job.status not in {
        AudioJobStatus.READY,
        AudioJobStatus.GENERATING,
        AudioJobStatus.PARTIALLY_FAILED,
        AudioJobStatus.REVIEW_REQUIRED,
        AudioJobStatus.COMPLETED,
    }:
        raise ChunkGenerationError(
            f"audio job {job.id} status {job.status.value} is not ready for generation"
        )

    if job.status in {
        AudioJobStatus.READY,
        AudioJobStatus.PARTIALLY_FAILED,
        AudioJobStatus.REVIEW_REQUIRED,
    }:
        repo.mark_job_generating(session, job.id, correlation_id=correlation_id)

    ordered = sorted(chunks, key=lambda item: item.chunk_index)
    try:
        assert_sufficient_credits_for_pending_chunks(client, job, ordered)
    except QuotaExceededError as exc:
        raise ChunkGenerationError(str(exc)) from exc

    completed = 0
    failed = 0
    skipped = 0

    for chunk in ordered:
        try:
            outcome = generate_single_chunk(
                session,
                repo,
                job,
                chunk,
                ordered,
                client,
                correlation_id=correlation_id,
            )
        except QuotaExceededError:
            break
        if outcome == "completed":
            completed += 1
        elif outcome == "failed":
            failed += 1
        else:
            skipped += 1

    return ChunkGenerationRunResult(completed=completed, failed=failed, skipped=skipped)
