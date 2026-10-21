"""Create TTS jobs from enhanced transcript versions."""

from tts_pipeline.intake.errors import AudioJobIntakeError, IntakeValidationError
from tts_pipeline.intake.chunk_idempotency import (
    TTS_CHUNK_IDEMPOTENCY_VERSION,
    build_chunk_idempotency_key,
)
from tts_pipeline.intake.chunk_idempotency import (
    TTS_CHUNK_IDEMPOTENCY_VERSION,
    build_chunk_idempotency_key,
)
from tts_pipeline.intake.idempotency import TTS_JOB_IDEMPOTENCY_VERSION, build_audio_job_idempotency_key
from tts_pipeline.intake.requests import CreateAudioJobRequest, CreateAudioJobResult
from tts_pipeline.intake.service import AUDIO_JOB_CREATED_EVENT, AudioJobIntakeService
from tts_pipeline.intake.validation import ALLOWED_TTS_TRANSCRIPT_STATUSES

__all__ = [
    "ALLOWED_TTS_TRANSCRIPT_STATUSES",
    "AUDIO_JOB_CREATED_EVENT",
    "AudioJobIntakeError",
    "AudioJobIntakeService",
    "CreateAudioJobRequest",
    "CreateAudioJobResult",
    "IntakeValidationError",
    "TTS_CHUNK_IDEMPOTENCY_VERSION",
    "TTS_JOB_IDEMPOTENCY_VERSION",
    "build_audio_job_idempotency_key",
    "build_chunk_idempotency_key",
]
