"""Consume TTS workflow jobs from SQS and run the orchestrator."""

from __future__ import annotations

from db.repositories import AudioJobRepository
from db.session import build_session_factory, session_scope
from models.enums import AudioJobStatus
from models.messages import TtsAudioJobMessage
from models.records import TranscriptAudioJobRecord
from observability.tts import configure_tts_logging, log_tts_replay
from queues.tts_consumer import TtsHandoffOutcome, TtsWorkflowHandoffHandler
from tts_pipeline.orchestrator import TtsWorkflowEngine, WorkflowInput, WorkflowState


def resolve_workflow_start_state(
    job: TranscriptAudioJobRecord,
    *,
    has_final_asset: bool,
    has_master_asset: bool,
) -> WorkflowState | None:
    """Pick orchestrator entry point for SQS replay (idempotent)."""
    if job.status is AudioJobStatus.COMPLETED:
        return None
    if has_final_asset and not has_master_asset:
        return WorkflowState.MIX_BACKGROUND
    return WorkflowState.LOAD_ENHANCED_TRANSCRIPT


class TtsWorkflowConsumerService(TtsWorkflowHandoffHandler):
    """Run the full TTS workflow for an audio job id from SQS."""

    def __init__(
        self,
        *,
        repository: AudioJobRepository | None = None,
        engine: TtsWorkflowEngine | None = None,
        database_url: str | None = None,
    ) -> None:
        configure_tts_logging()
        session_factory = build_session_factory(database_url)
        self._repository = repository or AudioJobRepository(session_factory)
        self._engine = engine or TtsWorkflowEngine(session_factory)

    def handle(self, message: TtsAudioJobMessage) -> str:
        correlation_id = message.correlation_id

        with session_scope(self._repository._session_factory) as session:
            job = self._repository.get_audio_job(session, message.audio_job_id)
            if job is None:
                raise ValueError(f"audio job {message.audio_job_id} not found")
            if job.tenant_id != message.tenant_id:
                raise PermissionError("tenant mismatch for TTS workflow handoff")

            has_final = self._repository.find_final_asset(session, job.id) is not None
            has_master = self._repository.find_master_asset(session, job.id) is not None
            start_state = resolve_workflow_start_state(
                job,
                has_final_asset=has_final,
                has_master_asset=has_master,
            )
            if start_state is None:
                log_tts_replay(
                    correlation_id=correlation_id,
                    audio_job_id=str(message.audio_job_id),
                    start_state=f"skipped_{job.status.value.lower()}",
                )
                return TtsHandoffOutcome.SKIPPED_DUPLICATE

            if start_state is WorkflowState.MIX_BACKGROUND:
                self._repository.reset_job_retry_count(
                    session,
                    job.id,
                    correlation_id=correlation_id,
                )
                self._repository.mark_job_generating(
                    session,
                    job.id,
                    correlation_id=correlation_id,
                )
                log_tts_replay(
                    correlation_id=correlation_id,
                    audio_job_id=str(message.audio_job_id),
                    start_state=WorkflowState.MIX_BACKGROUND.value,
                )

        result = self._engine.run(
            WorkflowInput(
                audio_job_id=message.audio_job_id,
                start_state=start_state,
                correlation_id=correlation_id,
            )
        )
        if not result.success:
            raise RuntimeError(result.error or f"TTS workflow failed at {result.final_state.value}")
        return TtsHandoffOutcome.PROCESSED
