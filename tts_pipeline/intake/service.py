"""Create TTS audio jobs from enhanced transcript versions."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from db.exceptions import DuplicateAudioJobError, TranscriptNotFoundError, TranscriptVersionNotFoundError
from db.repositories import AudioJobRepository, CreateAudioJobInput, TranscriptRepository
from models.enums import AudioJobStatus
from tts_pipeline.persistence.session import tts_session_scope
from tts_pipeline.intake.errors import IntakeValidationError
from tts_pipeline.intake.idempotency import build_audio_job_idempotency_key
from tts_pipeline.intake.metadata import build_audio_job_metadata
from tts_pipeline.intake.requests import CreateAudioJobRequest, CreateAudioJobResult
from tts_pipeline.intake.validation import validate_enhanced_version, validate_transcript_for_tts
from observability.tts import log_tts_job_created, tts_context_from_job
from tts_pipeline.voice_policy import (
    VoicePolicyError,
    get_voice_profile,
    resolve_enable_logging,
    resolve_seed,
)

AUDIO_JOB_CREATED_EVENT = "AUDIO_JOB_CREATED"


class AudioJobIntakeService:
    """Validate enhanced transcripts and persist audio jobs before generation."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        transcript_repository: TranscriptRepository | None = None,
        audio_job_repository: AudioJobRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._transcript_repo = transcript_repository or TranscriptRepository(session_factory)
        self._audio_job_repo = audio_job_repository or AudioJobRepository(session_factory)

    def create_audio_job(self, request: CreateAudioJobRequest) -> CreateAudioJobResult:
        with tts_session_scope(
            self._session_factory,
            correlation_id=request.correlation_id,
            audio_job_id=request.audio_job_id,
        ) as session:
            return self._create_audio_job(session, request)

    def _create_audio_job(
        self,
        session: Session,
        request: CreateAudioJobRequest,
    ) -> CreateAudioJobResult:
        try:
            profile = get_voice_profile(request.voice_profile_code)
        except VoicePolicyError as exc:
            raise IntakeValidationError(str(exc)) from exc

        try:
            transcript = self._transcript_repo.get_transcript(session, request.transcript_id)
            version = self._transcript_repo.get_transcript_version(
                session,
                request.transcript_id,
                request.transcript_version_id,
            )
        except TranscriptNotFoundError as exc:
            raise IntakeValidationError(str(exc)) from exc
        except TranscriptVersionNotFoundError as exc:
            raise IntakeValidationError(str(exc)) from exc

        validate_transcript_for_tts(transcript, tenant_id=request.tenant_id)
        validate_enhanced_version(version, transcript_id=request.transcript_id)

        idempotency_key = request.idempotency_key or build_audio_job_idempotency_key(
            transcript_id=request.transcript_id,
            transcript_version_id=request.transcript_version_id,
            voice_profile_code=request.voice_profile_code,
        )

        existing = self._audio_job_repo.find_audio_job_by_idempotency_key(session, idempotency_key)
        if existing is not None:
            log_tts_job_created(
                **tts_context_from_job(
                    existing,
                    correlation_id=request.correlation_id,
                    created=False,
                    idempotent=True,
                )
            )
            return CreateAudioJobResult(
                audio_job=existing,
                transcript=transcript,
                transcript_version=version,
                created=False,
            )

        try:
            seed = resolve_seed(profile, requested_seed=request.seed_override)
            enable_logging = resolve_enable_logging(profile)
        except VoicePolicyError as exc:
            raise IntakeValidationError(str(exc)) from exc

        metadata_json = build_audio_job_metadata(
            transcript=transcript,
            transcript_version=version,
            voice_profile_code=request.voice_profile_code,
            correlation_id=request.correlation_id,
        )

        try:
            audio_job = self._audio_job_repo.create_audio_job(
                session,
                CreateAudioJobInput(
                    audio_job_id=request.audio_job_id,
                    transcript_id=request.transcript_id,
                    transcript_version_id=request.transcript_version_id,
                    tenant_id=request.tenant_id,
                    idempotency_key=idempotency_key,
                    voice_profile_code=request.voice_profile_code,
                    voice_id=profile.voice_id,
                    model_id=profile.default_model_id,
                    output_format=profile.default_output_format,
                    enable_logging=enable_logging,
                    apply_text_normalization=profile.default_apply_text_normalization,
                    seed=seed,
                    metadata_json=metadata_json,
                    status=AudioJobStatus.CREATED,
                ),
                correlation_id=request.correlation_id,
            )
        except DuplicateAudioJobError:
            existing = self._audio_job_repo.find_audio_job_by_idempotency_key(session, idempotency_key)
            if existing is None:
                raise
            return CreateAudioJobResult(
                audio_job=existing,
                transcript=transcript,
                transcript_version=version,
                created=False,
            )

        self._audio_job_repo.record_audio_event(
            session,
            audio_job.id,
            AUDIO_JOB_CREATED_EVENT,
            {
                "transcript_id": str(request.transcript_id),
                "transcript_version_id": str(request.transcript_version_id),
                "tenant_id": str(request.tenant_id),
                "voice_profile_code": request.voice_profile_code,
                "idempotency_key": idempotency_key,
                "status": AudioJobStatus.CREATED.value,
            },
            correlation_id=request.correlation_id,
        )

        log_tts_job_created(
            **tts_context_from_job(
                audio_job,
                correlation_id=request.correlation_id,
                created=True,
                voice_profile_code=request.voice_profile_code,
            )
        )

        return CreateAudioJobResult(
            audio_job=audio_job,
            transcript=transcript,
            transcript_version=version,
            created=True,
        )
