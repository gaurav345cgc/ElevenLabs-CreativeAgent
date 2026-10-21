"""When to escalate TTS jobs to REVIEW_REQUIRED instead of retryable failure."""

from __future__ import annotations

from models.enums import AudioChunkStatus
from models.records import TranscriptAudioChunkRecord, TranscriptAudioJobRecord
from tts_pipeline.generator.chunk_generation import (
    ChunkGenerationError,
    is_permanent_generation_error,
    is_transient_generation_error,
)
from tts_pipeline.finalizer import FinalAudioMergeError
from tts_pipeline.orchestrator.errors import WorkflowValidationError

DEFAULT_MAX_WORKFLOW_RETRIES = 3

WORKFLOW_REVIEW_REQUIRED_EVENT = "WORKFLOW_REVIEW_REQUIRED"

PERMANENT_CHUNK_ERROR_CODES = frozenset(
    {
        "ChunkGenerationError",
        "WorkflowValidationError",
        "ValueError",
    }
)


def chunk_failure_requires_review(chunk: TranscriptAudioChunkRecord) -> bool:
    """True when a failed chunk error is not safe to auto-retry."""
    if chunk.status is not AudioChunkStatus.FAILED:
        return False

    if chunk.error_code in PERMANENT_CHUNK_ERROR_CODES:
        return True

    metadata = chunk.metadata_json or {}
    status_code = metadata.get("provider_status_code")
    if isinstance(status_code, int) and not _is_transient_status_code(status_code):
        return True

    if metadata.get("provider_error_code") == "quota_exceeded":
        return True

    return False


def should_escalate_job_to_review(
    job: TranscriptAudioJobRecord,
    chunks: list[TranscriptAudioChunkRecord],
    *,
    error: BaseException | None = None,
) -> bool:
    """Decide whether operators must intervene before another replay."""
    if error is not None and _workflow_error_requires_review(error):
        return True

    if job.retry_count >= DEFAULT_MAX_WORKFLOW_RETRIES:
        return True

    failed_chunks = [chunk for chunk in chunks if chunk.status is AudioChunkStatus.FAILED]
    if failed_chunks and any(chunk_failure_requires_review(chunk) for chunk in failed_chunks):
        return True

    return False


def _workflow_error_requires_review(error: BaseException) -> bool:
    if isinstance(error, (WorkflowValidationError, ChunkGenerationError)):
        return True
    if isinstance(error, FinalAudioMergeError):
        # Stitch/mix infra failures (e.g. Lambda /tmp full) are retried after ops fixes — not operator script review.
        lowered = str(error).lower()
        if "no space left" in lowered or "background mix failed" in lowered:
            return False
    return is_permanent_generation_error(error)


def _is_transient_status_code(status_code: int) -> bool:
    from tts_pipeline.generator.elevenlabs_client import ElevenLabsApiError

    return is_transient_generation_error(ElevenLabsApiError("probe", status_code=status_code))
