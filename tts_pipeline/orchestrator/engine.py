"""Local workflow engine — mirrors Step Functions Standard state order."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session, sessionmaker

from db.repositories import AudioJobRepository, TranscriptRepository
from observability.tts import (
    log_tts_pause_plan_failed,
    log_tts_replay,
    log_tts_workflow_failed,
    log_tts_workflow_started,
    log_tts_workflow_state,
    log_tts_workflow_succeeded,
    tts_context_from_job,
)
from tts_pipeline.generator import ElevenLabsClient
from tts_pipeline.orchestrator.config import DEFAULT_ORCHESTRATOR, STATE_POLICIES
from tts_pipeline.orchestrator.context import WorkflowContext
from tts_pipeline.finalizer import FinalAudioMergeError
from tts_pipeline.generator.chunk_generation import ChunkGenerationError
from tts_pipeline.orchestrator.errors import OrchestratorError, WorkflowStateError, WorkflowValidationError
from tts_pipeline.orchestrator.states import (
    create_audio_job,
    finalize_final,
    finalize_manifest_only,
    generate_chunks,
    handle_failure,
    load_enhanced_transcript,
    map_pauses_to_chunks,
    mark_completed,
    mix_background,
    plan_and_persist_chunks,
    plan_pauses,
    register_assets,
    reload_job_and_chunks,
    validate_input,
)
from tts_pipeline.orchestrator.workflow import WorkflowInput, WorkflowResult, WorkflowState
from tts_pipeline.pause_planner.errors import (
    PausePlannerError,
    PausePlannerTransientError,
    PausePlannerValidationError,
)
from tts_pipeline.persistence.session import tts_session_scope


class TtsWorkflowEngine:
    """Run the TTS job lifecycle locally or from a Step Functions task handler."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        elevenlabs_client: ElevenLabsClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._transcript_repo = TranscriptRepository(session_factory)
        self._audio_repo = AudioJobRepository(session_factory)
        self._client = elevenlabs_client or ElevenLabsClient.from_env()

    def run(self, workflow_input: WorkflowInput) -> WorkflowResult:
        correlation_id = workflow_input.correlation_id or str(uuid.uuid4())
        ctx = WorkflowContext(correlation_id=correlation_id, audio_job_id=workflow_input.audio_job_id)

        log_tts_workflow_started(
            correlation_id=correlation_id,
            start_state=workflow_input.start_state.value,
            audio_job_id=str(workflow_input.audio_job_id) if workflow_input.audio_job_id else None,
            orchestrator=DEFAULT_ORCHESTRATOR,
        )
        if workflow_input.start_state.value != WorkflowState.VALIDATE_INPUT.value:
            log_tts_replay(
                correlation_id=correlation_id,
                audio_job_id=str(workflow_input.audio_job_id) if workflow_input.audio_job_id else None,
                start_state=workflow_input.start_state.value,
            )

        state = workflow_input.start_state
        try:
            if state is WorkflowState.VALIDATE_INPUT:
                validate_input(ctx, workflow_input)
            elif workflow_input.audio_job_id is None:
                raise WorkflowValidationError("audio_job_id is required when not starting at ValidateInput")
            else:
                ctx.audio_job_id = workflow_input.audio_job_id

            while state is not WorkflowState.SUCCEEDED:
                state = self._run_state(state, ctx, workflow_input)
            assert ctx.audio_job_id is not None
            log_tts_workflow_succeeded(
                correlation_id=correlation_id,
                audio_job_id=str(ctx.audio_job_id),
            )
            return WorkflowResult(
                audio_job_id=ctx.audio_job_id,
                final_state=WorkflowState.SUCCEEDED,
                correlation_id=correlation_id,
                success=True,
            )
        except (
            OrchestratorError,
            ChunkGenerationError,
            FinalAudioMergeError,
            PausePlannerError,
        ) as exc:
            ctx.last_error = str(exc)
            job_id = ctx.audio_job_id or workflow_input.audio_job_id
            if job_id is not None:
                with tts_session_scope(
                    self._session_factory,
                    correlation_id=correlation_id,
                    audio_job_id=job_id,
                ) as session:
                    handle_failure(session, self._audio_repo, ctx, error=exc)
                log_tts_workflow_failed(
                    correlation_id=correlation_id,
                    audio_job_id=str(job_id),
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                return WorkflowResult(
                    audio_job_id=job_id,
                    final_state=WorkflowState.FAILURE_HANDLER,
                    correlation_id=correlation_id,
                    success=False,
                    error=str(exc),
                )
            raise

    def _run_state(
        self,
        state: WorkflowState,
        ctx: WorkflowContext,
        workflow_input: WorkflowInput,
    ) -> WorkflowState:
        policy = STATE_POLICIES.get(state.value)
        log_tts_workflow_state(
            correlation_id=ctx.correlation_id,
            state=state.value,
            timeout_seconds=policy.timeout_seconds if policy else None,
            max_attempts=policy.max_attempts if policy else None,
            audio_job_id=str(ctx.audio_job_id) if ctx.audio_job_id else None,
        )

        if state is WorkflowState.VALIDATE_INPUT:
            return WorkflowState.CREATE_AUDIO_JOB

        if state is WorkflowState.CREATE_AUDIO_JOB:
            create_audio_job(self._session_factory, ctx, workflow_input)
            return WorkflowState.LOAD_ENHANCED_TRANSCRIPT

        if state in {
            WorkflowState.LOAD_ENHANCED_TRANSCRIPT,
            WorkflowState.PLAN_PAUSES,
            WorkflowState.PLAN_CHUNKS,
            WorkflowState.MAP_PAUSES_TO_CHUNKS,
            WorkflowState.PERSIST_CHUNK_PLAN,
            WorkflowState.GENERATE_CHUNKS_SEQUENTIALLY,
            WorkflowState.REGISTER_ASSETS,
            WorkflowState.FINALIZE_FINAL,
            WorkflowState.MIX_BACKGROUND,
            WorkflowState.FINALIZE_MANIFEST,
            WorkflowState.MARK_COMPLETED,
        }:
            return self._run_session_state(state, ctx)

        raise WorkflowValidationError(f"unsupported workflow state {state.value}")

    def _run_session_state(self, state: WorkflowState, ctx: WorkflowContext) -> WorkflowState:
        with tts_session_scope(
            self._session_factory,
            correlation_id=ctx.correlation_id,
            audio_job_id=ctx.audio_job_id,
        ) as session:
            if state is WorkflowState.LOAD_ENHANCED_TRANSCRIPT:
                load_enhanced_transcript(session, self._transcript_repo, ctx)
                return WorkflowState.PLAN_PAUSES

            if state is WorkflowState.PLAN_PAUSES:
                self._run_plan_pauses_with_retries(session, ctx)
                return WorkflowState.PLAN_CHUNKS

            if state is WorkflowState.PLAN_CHUNKS:
                plan_and_persist_chunks(self._session_factory, ctx)
                return WorkflowState.MAP_PAUSES_TO_CHUNKS

            if state is WorkflowState.MAP_PAUSES_TO_CHUNKS:
                self._run_map_pauses_with_retries(session, ctx)
                return WorkflowState.PERSIST_CHUNK_PLAN

            if state is WorkflowState.PERSIST_CHUNK_PLAN:
                reload_job_and_chunks(session, self._audio_repo, ctx)
                if not ctx.chunks:
                    raise WorkflowValidationError("chunk plan is empty after persistence")
                return WorkflowState.GENERATE_CHUNKS_SEQUENTIALLY

            if state is WorkflowState.GENERATE_CHUNKS_SEQUENTIALLY:
                try:
                    generate_chunks(session, self._audio_repo, ctx, self._client)
                except ChunkGenerationError:
                    raise
                return WorkflowState.REGISTER_ASSETS

            if state is WorkflowState.REGISTER_ASSETS:
                register_assets(session, self._audio_repo, ctx)
                return WorkflowState.FINALIZE_FINAL

            if state is WorkflowState.FINALIZE_FINAL:
                finalize_final(session, self._audio_repo, ctx)
                return WorkflowState.MIX_BACKGROUND

            if state is WorkflowState.MIX_BACKGROUND:
                mix_background(session, self._audio_repo, ctx)
                return WorkflowState.FINALIZE_MANIFEST

            if state is WorkflowState.FINALIZE_MANIFEST:
                finalize_manifest_only(session, self._audio_repo, ctx)
                return WorkflowState.MARK_COMPLETED

            if state is WorkflowState.MARK_COMPLETED:
                mark_completed(session, self._audio_repo, ctx)
                return WorkflowState.SUCCEEDED

        raise WorkflowValidationError(f"unhandled session state {state.value}")

    def _run_plan_pauses_with_retries(self, session: Session, ctx: WorkflowContext) -> None:
        """Retry transient planner errors; validation errors fail the job immediately."""
        policy = STATE_POLICIES.get(WorkflowState.PLAN_PAUSES.value)
        max_attempts = policy.max_attempts if policy else 1
        last_error: PausePlannerTransientError | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                plan_pauses(session, self._audio_repo, self._transcript_repo, ctx)
                return
            except PausePlannerValidationError as exc:
                self._log_pause_plan_failure(ctx, error=exc, attempt=attempt, final=True)
                raise
            except PausePlannerTransientError as exc:
                last_error = exc
                if attempt >= max_attempts:
                    self._log_pause_plan_failure(ctx, error=exc, attempt=attempt, final=True)
                    raise WorkflowStateError(
                        f"PlanPauses failed after {max_attempts} attempts: {exc}"
                    ) from exc
            except PausePlannerError as exc:
                self._log_pause_plan_failure(ctx, error=exc, attempt=attempt, final=True)
                raise WorkflowStateError(f"PlanPauses failed: {exc}") from exc
        if last_error is not None:
            self._log_pause_plan_failure(ctx, error=last_error, attempt=max_attempts, final=True)
            raise WorkflowStateError(f"PlanPauses failed: {last_error}") from last_error

    def _log_pause_plan_failure(
        self,
        ctx: WorkflowContext,
        *,
        error: BaseException,
        attempt: int,
        final: bool,
    ) -> None:
        context: dict[str, object] = {
            "correlation_id": ctx.correlation_id,
            "audio_job_id": str(ctx.audio_job_id) if ctx.audio_job_id else None,
            "error": str(error),
            "error_type": type(error).__name__,
            "attempt": attempt,
            "final": final,
        }
        if ctx.job is not None:
            context = {
                **tts_context_from_job(ctx.job, correlation_id=ctx.correlation_id),
                "error": str(error),
                "error_type": type(error).__name__,
                "attempt": attempt,
                "final": final,
            }
        log_tts_pause_plan_failed(**context)

    def _run_map_pauses_with_retries(self, session: Session, ctx: WorkflowContext) -> None:
        """Retry transient mapping failures; validation errors fail immediately."""
        policy = STATE_POLICIES.get(WorkflowState.MAP_PAUSES_TO_CHUNKS.value)
        max_attempts = policy.max_attempts if policy else 1
        last_error: PausePlannerTransientError | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                map_pauses_to_chunks(session, self._audio_repo, self._transcript_repo, ctx)
                return
            except PausePlannerValidationError:
                raise
            except PausePlannerTransientError as exc:
                last_error = exc
                if attempt >= max_attempts:
                    raise WorkflowStateError(
                        f"MapPausesToChunks failed after {max_attempts} attempts: {exc}"
                    ) from exc
            except PausePlannerError as exc:
                raise WorkflowStateError(f"MapPausesToChunks failed: {exc}") from exc
        if last_error is not None:
            raise WorkflowStateError(f"MapPausesToChunks failed: {last_error}") from last_error
