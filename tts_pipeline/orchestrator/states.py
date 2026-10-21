"""Workflow state handlers — mirror infra/step_functions/tts_audio_job.asl.json."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from db.repositories import AudioJobRepository, TranscriptRepository
from models.enums import AudioChunkStatus, AudioJobStatus, VersionKind
from models.records import TranscriptAudioChunkRecord, TranscriptAudioJobRecord, TranscriptVersionRecord
from observability.tts import (
    log_tts_job_completed,
    log_tts_job_failed,
    log_tts_job_partially_failed,
    log_tts_job_review_required,
    log_tts_pause_plan_created,
    log_tts_pause_plan_latency,
    log_tts_pause_plan_reused,
    tts_context_from_job,
)
from tts_pipeline.chunk_planner import ChunkPlanningService
from tts_pipeline.chunk_planner.models import ChunkBoundarySource, PlannedChunk
from tts_pipeline.chunk_planner.planner import estimate_chunk_duration_ms
from tts_pipeline.generator import ElevenLabsClient
from tts_pipeline.intake import AudioJobIntakeService
from tts_pipeline.orchestrator.context import WorkflowContext
from tts_pipeline.orchestrator.errors import WorkflowStateError, WorkflowValidationError
from tts_pipeline.generator.chunk_generation import ChunkGenerationError
from tts_pipeline.orchestrator.generation import generate_chunks_sequentially
from tts_pipeline.orchestrator.review_escalation import (
    WORKFLOW_REVIEW_REQUIRED_EVENT,
    should_escalate_job_to_review,
)
from tts_pipeline.orchestrator.workflow import WorkflowInput
from tts_pipeline.pause_planner import (
    OpenAIPausePlannerClient,
    create_or_load_pause_plan,
    extract_pause_anchors,
    map_pause_plan_to_chunks,
    parse_pause_plan_response,
    persist_mapped_pause_plan,
    validate_pause_plan_anchors,
)
from tts_pipeline.pause_planner.density import enforce_pause_density
from tts_pipeline.pause_planner.human_markers import load_human_pause_plan
from tts_pipeline.pause_planner.schema import PausePlan
from tts_pipeline.pause_planner.service import (
    PAUSE_PLAN_KEY,
    PlanFactory,
    SessionPausePlanStore,
)
from tts_pipeline.finalizer import (
    finalize_audio_job_final,
    finalize_audio_job_manifest,
    finalize_audio_job_master,
)

DEFAULT_TARGET_DURATION_SECONDS = 600


ASSETS_REGISTERED_EVENT = "ASSETS_REGISTERED"
WORKFLOW_COMPLETED_EVENT = "WORKFLOW_COMPLETED"


def _resolve_job_failure(
    session: Session,
    audio_repo: AudioJobRepository,
    ctx: WorkflowContext,
    *,
    last_error: str,
    partially_failed: bool,
    error: BaseException | None = None,
    increment_retry_count: bool = True,
) -> None:
    assert ctx.audio_job_id is not None
    job = ctx.job
    if increment_retry_count:
        job = audio_repo.increment_job_retry_count(
            session,
            ctx.audio_job_id,
            correlation_id=ctx.correlation_id,
        )
        ctx.job = job

    reload_job_and_chunks(session, audio_repo, ctx)
    assert ctx.job is not None

    if should_escalate_job_to_review(ctx.job, ctx.chunks, error=error):
        audio_repo.mark_job_review_required(
            session,
            ctx.audio_job_id,
            last_error=last_error,
            failure_notes=f"retry_count={ctx.job.retry_count}",
            correlation_id=ctx.correlation_id,
        )
        log_tts_job_review_required(
            **tts_context_from_job(
                ctx.job,
                correlation_id=ctx.correlation_id,
                error=last_error,
                partially_failed=partially_failed,
                retry_count=ctx.job.retry_count,
            )
        )
        audio_repo.record_audio_event(
            session,
            ctx.audio_job_id,
            WORKFLOW_REVIEW_REQUIRED_EVENT,
            {
                "error": last_error,
                "retry_count": ctx.job.retry_count,
                "partially_failed": partially_failed,
            },
            correlation_id=ctx.correlation_id,
        )
    else:
        audio_repo.mark_job_failed(
            session,
            ctx.audio_job_id,
            last_error=last_error,
            partially_failed=partially_failed,
            correlation_id=ctx.correlation_id,
        )
        if partially_failed:
            log_tts_job_partially_failed(
                **tts_context_from_job(
                    ctx.job,
                    correlation_id=ctx.correlation_id,
                    error=last_error,
                    retry_count=ctx.job.retry_count,
                )
            )
        else:
            log_tts_job_failed(
                **tts_context_from_job(
                    ctx.job,
                    correlation_id=ctx.correlation_id,
                    error=last_error,
                    retry_count=ctx.job.retry_count,
                )
            )
        audio_repo.record_audio_event(
            session,
            ctx.audio_job_id,
            "WORKFLOW_FAILED",
            {"error": last_error, "retry_count": ctx.job.retry_count},
            correlation_id=ctx.correlation_id,
        )

    ctx.job = audio_repo.get_audio_job(session, ctx.audio_job_id)


def validate_input(ctx: WorkflowContext, workflow_input: WorkflowInput) -> None:
    if workflow_input.audio_job_id is None and workflow_input.create_job_request is None:
        raise WorkflowValidationError("Provide audio_job_id or create_job_request")


def create_audio_job(
    session_factory: sessionmaker,
    ctx: WorkflowContext,
    workflow_input: WorkflowInput,
) -> None:
    if workflow_input.audio_job_id is not None:
        ctx.audio_job_id = workflow_input.audio_job_id
        return
    if workflow_input.create_job_request is None:
        raise WorkflowValidationError("create_job_request is required when audio_job_id is absent")

    intake = AudioJobIntakeService(session_factory)
    result = intake.create_audio_job(workflow_input.create_job_request)
    ctx.audio_job_id = result.audio_job.id
    ctx.job = result.audio_job
    ctx.tenant_id = result.transcript.tenant_id
    ctx.transcript_id = result.transcript.id
    ctx.transcript_version_id = result.transcript_version.id
    ctx.voice_profile_code = result.audio_job.voice_profile_code


def load_enhanced_transcript(
    session: Session,
    transcript_repo: TranscriptRepository,
    ctx: WorkflowContext,
) -> None:
    if ctx.audio_job_id is None:
        raise WorkflowStateError("audio_job_id missing before LoadEnhancedTranscript")

    job = ctx.job
    if job is None:
        audio_repo = AudioJobRepository(transcript_repo._session_factory)
        job = audio_repo.get_audio_job(session, ctx.audio_job_id)
        if job is None:
            raise WorkflowValidationError(f"audio job {ctx.audio_job_id} not found")
        ctx.job = job

    version = transcript_repo.get_transcript_version(
        session,
        job.transcript_id,
        job.transcript_version_id,
    )
    if version.version_kind not in {VersionKind.ELEVENLABS_ENHANCED, VersionKind.APPROVED_FINAL}:
        raise WorkflowValidationError(
            f"transcript version {version.id} is not ELEVENLABS_ENHANCED or APPROVED_FINAL"
        )

    ctx.transcript_version = version
    ctx.tenant_id = job.tenant_id
    ctx.transcript_id = job.transcript_id
    ctx.transcript_version_id = job.transcript_version_id
    ctx.voice_profile_code = job.voice_profile_code


def plan_and_persist_chunks(
    session_factory: sessionmaker,
    ctx: WorkflowContext,
) -> None:
    if ctx.audio_job_id is None:
        raise WorkflowStateError("audio_job_id missing before PlanChunks")

    planner = ChunkPlanningService(session_factory)
    result = planner.plan_and_persist(
        ctx.audio_job_id,
        correlation_id=ctx.correlation_id,
    )
    ctx.chunks = result.persisted_chunks or []
    ctx.metadata["boundary_source"] = result.boundary_source.value
    ctx.metadata["chunk_plan_created"] = result.created


def plan_pauses(
    session: Session,
    audio_repo: AudioJobRepository,
    transcript_repo: TranscriptRepository,
    ctx: WorkflowContext,
    *,
    plan_factory: PlanFactory | None = None,
    pause_planner_client: OpenAIPausePlannerClient | None = None,
    force_replan: bool = False,
) -> None:
    """OpenAI pause plan + normalize + persist ``pause_plan`` (idempotent)."""
    if ctx.audio_job_id is None:
        raise WorkflowStateError("audio_job_id missing before PlanPauses")

    reload_job_and_chunks(session, audio_repo, ctx)
    assert ctx.job is not None
    version = _load_transcript_version(session, transcript_repo, ctx, ctx.job)
    anchors = extract_pause_anchors(version)

    target_duration_seconds = _resolve_target_duration_seconds(ctx.job, version)
    estimated_speech_seconds = _resolve_estimated_speech_seconds(ctx.job, version)

    store = SessionPausePlanStore(
        session=session,
        repository=audio_repo,
        audio_job_id=ctx.audio_job_id,
        correlation_id=ctx.correlation_id,
    )
    factory = plan_factory or _build_plan_factory(
        version=version,
        anchors=anchors,
        target_duration_seconds=target_duration_seconds,
        estimated_speech_seconds=estimated_speech_seconds,
        pause_planner_client=pause_planner_client,
    )
    started = time.perf_counter()
    result = create_or_load_pause_plan(
        store,
        plan_factory=factory,
        force_replan=force_replan,
        target_duration_seconds=target_duration_seconds,
        estimated_speech_seconds=estimated_speech_seconds,
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    if pause_planner_client is not None and pause_planner_client.last_latency_ms is not None:
        latency_ms = float(pause_planner_client.last_latency_ms)

    ctx.job = audio_repo.get_audio_job(session, ctx.audio_job_id)
    ctx.transcript_version = version
    ctx.metadata["pause_plan_hold_count"] = len(result.plan.holds)
    ctx.metadata["pause_plan_total_hold_seconds"] = result.plan.total_hold_seconds
    ctx.metadata["pause_plan_created"] = result.created
    ctx.metadata["pause_plan_reused"] = result.reused
    ctx.metadata["pause_plan_clamped"] = result.clamped
    ctx.metadata["pause_anchors_preferred"] = anchors.preferred
    ctx.metadata["pause_target_duration_seconds"] = target_duration_seconds
    ctx.metadata["pause_estimated_speech_seconds"] = estimated_speech_seconds

    assert ctx.job is not None
    pause_context = tts_context_from_job(
        ctx.job,
        correlation_id=ctx.correlation_id,
        hold_count=len(result.plan.holds),
        total_hold_seconds=result.plan.total_hold_seconds,
        model=result.plan.model,
        prompt_version=result.plan.prompt_version,
        policy_version=result.plan.policy_version,
        clamped=result.clamped,
    )
    if result.created:
        log_tts_pause_plan_created(**pause_context)
        log_tts_pause_plan_latency(latency_ms=latency_ms, **pause_context)
    else:
        log_tts_pause_plan_reused(**pause_context)


def map_pauses_to_chunks(
    session: Session,
    audio_repo: AudioJobRepository,
    transcript_repo: TranscriptRepository,
    ctx: WorkflowContext,
) -> None:
    """Map stored ``pause_plan`` onto chunk indices; persist ``mapped_pause_plan``.

    Does not call OpenAI — safe to replay independently of ``PlanPauses``.
    """
    if ctx.audio_job_id is None:
        raise WorkflowStateError("audio_job_id missing before MapPausesToChunks")

    reload_job_and_chunks(session, audio_repo, ctx)
    assert ctx.job is not None

    raw_plan = (ctx.job.metadata_json or {}).get(PAUSE_PLAN_KEY)
    if not raw_plan:
        raise WorkflowStateError(
            f"audio job {ctx.audio_job_id} missing pause_plan before MapPausesToChunks"
        )
    plan = raw_plan if isinstance(raw_plan, PausePlan) else PausePlan.model_validate(raw_plan)

    if not ctx.chunks:
        raise WorkflowStateError(
            f"audio job {ctx.audio_job_id} has no planned chunks before MapPausesToChunks"
        )

    version = _load_transcript_version(session, transcript_repo, ctx, ctx.job)
    anchors = extract_pause_anchors(version)
    planned = _planned_chunks_from_records(ctx.chunks, ctx.job)
    mapped = map_pause_plan_to_chunks(plan, planned, anchors)

    store = SessionPausePlanStore(
        session=session,
        repository=audio_repo,
        audio_job_id=ctx.audio_job_id,
        correlation_id=ctx.correlation_id,
    )
    persist_mapped_pause_plan(store, mapped)
    ctx.job = audio_repo.get_audio_job(session, ctx.audio_job_id)
    ctx.transcript_version = version
    ctx.metadata["mapped_pause_hold_count"] = len(mapped.holds)
    ctx.metadata["mapped_pause_total_hold_seconds"] = mapped.total_hold_seconds
    ctx.metadata["mapped_pause_after_chunk_indexes"] = [
        hold.after_chunk_index for hold in mapped.holds
    ]


def _load_transcript_version(
    session: Session,
    transcript_repo: TranscriptRepository,
    ctx: WorkflowContext,
    job: TranscriptAudioJobRecord,
) -> TranscriptVersionRecord:
    if (
        ctx.transcript_version is not None
        and ctx.transcript_version.id == job.transcript_version_id
    ):
        return ctx.transcript_version
    version = transcript_repo.get_transcript_version(
        session,
        job.transcript_id,
        job.transcript_version_id,
    )
    ctx.transcript_version = version
    return version


def _resolve_target_duration_seconds(
    job: TranscriptAudioJobRecord,
    version: TranscriptVersionRecord,
) -> int:
    for source in _duration_metadata_candidates(job, version):
        resolved = _duration_seconds_from_mapping(source)
        if resolved is not None:
            return resolved
    return DEFAULT_TARGET_DURATION_SECONDS


def _duration_metadata_candidates(
    job: TranscriptAudioJobRecord,
    version: TranscriptVersionRecord,
) -> list[dict[str, Any]]:
    """Job top-level → version → nested intake traceability → briefs."""
    candidates: list[dict[str, Any]] = []
    for mapping in (job.metadata_json or {}, version.metadata_json or {}):
        if not isinstance(mapping, dict):
            continue
        candidates.append(mapping)
        brief = mapping.get("brief")
        if isinstance(brief, dict):
            candidates.append(brief)
        trace = mapping.get("traceability")
        if isinstance(trace, dict):
            tv = trace.get("transcript_version")
            if isinstance(tv, dict):
                nested = tv.get("metadata_json")
                if isinstance(nested, dict):
                    candidates.append(nested)
    return candidates


def _duration_seconds_from_mapping(mapping: dict[str, Any]) -> int | None:
    seconds = mapping.get("target_duration_seconds")
    if seconds is not None:
        return max(1, int(seconds))
    minutes = mapping.get("target_duration_minutes")
    if minutes is not None:
        return max(1, int(minutes) * 60)
    return None


def _resolve_estimated_speech_seconds(
    job: TranscriptAudioJobRecord,
    version: TranscriptVersionRecord,
) -> int:
    if job.estimated_duration_ms is not None:
        return max(0, int(round(job.estimated_duration_ms / 1000)))
    meta = job.metadata_json or {}
    if meta.get("estimated_speech_seconds") is not None:
        return max(0, int(meta["estimated_speech_seconds"]))
    # Prefer live text estimate over planned speech_budget so holds fill real remainder.
    ms = estimate_chunk_duration_ms(version.content_text or "")
    if ms > 0:
        return max(0, ms // 1000)
    for source in _duration_metadata_candidates(job, version):
        if source.get("speech_budget_seconds") is not None:
            return max(0, int(source["speech_budget_seconds"]))
        estimate = source.get("duration_estimate")
        if isinstance(estimate, dict) and estimate.get("seconds") is not None:
            return max(0, int(estimate["seconds"]))
    return 0


def _build_plan_factory(
    *,
    version: TranscriptVersionRecord,
    anchors,
    target_duration_seconds: int,
    estimated_speech_seconds: int,
    pause_planner_client: OpenAIPausePlannerClient | None,
) -> PlanFactory:
    """Prefer Script Hub human_pause_plan; otherwise call OpenAI."""

    def factory() -> PausePlan:
        human_plan = load_human_pause_plan(version.metadata_json)
        if human_plan is not None:
            # Re-stamp duration fields from this job so normalize budgeting is accurate.
            plan = human_plan.model_copy(
                update={
                    "target_duration_seconds": target_duration_seconds,
                    "estimated_speech_seconds": estimated_speech_seconds,
                }
            )
            validate_pause_plan_anchors(
                plan,
                beat_count=len(anchors.beats),
                paragraph_count=len(anchors.paragraphs),
            )
            # Gap-fill only — never remove reviewer-placed holds here.
            return enforce_pause_density(plan, anchors)

        client = pause_planner_client or OpenAIPausePlannerClient()
        raw = client.plan_pauses(
            beats=list(anchors.beats),
            paragraphs=list(anchors.paragraphs),
            target_duration_seconds=target_duration_seconds,
            estimated_speech_seconds=estimated_speech_seconds,
        )
        use_beats = anchors.preferred == "beats"
        plan = parse_pause_plan_response(
            raw,
            model=client.model,
            target_duration_seconds=target_duration_seconds,
            estimated_speech_seconds=estimated_speech_seconds,
            use_beats=use_beats,
        )
        validate_pause_plan_anchors(
            plan,
            beat_count=len(anchors.beats),
            paragraph_count=len(anchors.paragraphs),
        )
        return enforce_pause_density(plan, anchors)

    return factory


# Back-compat alias for tests / callers that still import the old name.
def _build_openai_plan_factory(
    *,
    anchors,
    target_duration_seconds: int,
    estimated_speech_seconds: int,
    pause_planner_client: OpenAIPausePlannerClient | None,
    version: TranscriptVersionRecord | None = None,
) -> PlanFactory:
    if version is None:
        # Synthetic empty version — OpenAI-only path used by older unit tests.
        from types import SimpleNamespace

        version = SimpleNamespace(metadata_json={})  # type: ignore[assignment]
    return _build_plan_factory(
        version=version,  # type: ignore[arg-type]
        anchors=anchors,
        target_duration_seconds=target_duration_seconds,
        estimated_speech_seconds=estimated_speech_seconds,
        pause_planner_client=pause_planner_client,
    )


def _planned_chunks_from_records(
    chunks: list[TranscriptAudioChunkRecord],
    job: TranscriptAudioJobRecord,
) -> list[PlannedChunk]:
    boundary_source = _boundary_source_from_job(job)
    return [
        PlannedChunk(
            chunk_index=chunk.chunk_index,
            source_text=chunk.source_text,
            previous_text=chunk.previous_text,
            next_text=chunk.next_text,
            character_count=chunk.character_count,
            estimated_duration_ms=chunk.estimated_duration_ms or 0,
            boundary_source=boundary_source,
        )
        for chunk in sorted(chunks, key=lambda row: row.chunk_index)
    ]


def _boundary_source_from_job(job: TranscriptAudioJobRecord) -> ChunkBoundarySource:
    raw = (job.metadata_json or {}).get("boundary_source")
    try:
        return ChunkBoundarySource(raw)
    except ValueError:
        return ChunkBoundarySource.PARAGRAPHS


def reload_job_and_chunks(
    session: Session,
    audio_repo: AudioJobRepository,
    ctx: WorkflowContext,
) -> None:
    if ctx.audio_job_id is None:
        raise WorkflowStateError("audio_job_id missing")
    ctx.job = audio_repo.get_audio_job(session, ctx.audio_job_id)
    if ctx.job is None:
        raise WorkflowValidationError(f"audio job {ctx.audio_job_id} not found")
    ctx.chunks = audio_repo.list_audio_chunks(session, ctx.audio_job_id)


def generate_chunks(
    session: Session,
    audio_repo: AudioJobRepository,
    ctx: WorkflowContext,
    client: ElevenLabsClient,
) -> None:
    if ctx.job is None or not ctx.chunks:
        reload_job_and_chunks(session, audio_repo, ctx)

    assert ctx.job is not None
    result = generate_chunks_sequentially(
        session,
        audio_repo,
        ctx.job,
        ctx.chunks,
        client,
        correlation_id=ctx.correlation_id,
    )
    reload_job_and_chunks(session, audio_repo, ctx)
    ctx.metadata["generation_completed"] = result.completed
    ctx.metadata["generation_failed"] = result.failed
    ctx.metadata["generation_skipped"] = result.skipped
    if result.failed and result.completed == 0 and result.skipped == 0:
        raise ChunkGenerationError("all chunks failed during generation")


def register_assets(
    session: Session,
    audio_repo: AudioJobRepository,
    ctx: WorkflowContext,
) -> None:
    reload_job_and_chunks(session, audio_repo, ctx)
    completed = [
        chunk for chunk in ctx.chunks if chunk.status is AudioChunkStatus.COMPLETED
    ]
    if not completed:
        raise WorkflowStateError("no completed chunks to register")

    audio_repo.record_audio_event(
        session,
        ctx.audio_job_id,
        ASSETS_REGISTERED_EVENT,
        {
            "chunk_count": len(completed),
            "object_keys": [chunk.output_object_key for chunk in completed if chunk.output_object_key],
        },
        correlation_id=ctx.correlation_id,
    )


def finalize_final(
    session: Session,
    audio_repo: AudioJobRepository,
    ctx: WorkflowContext,
    *,
    s3_client=None,
) -> None:
    """Stitch completed chunks into final.mp3 and register the FINAL asset."""
    reload_job_and_chunks(session, audio_repo, ctx)
    assert ctx.job is not None

    final_result = finalize_audio_job_final(
        session,
        audio_repo,
        ctx.job,
        ctx.chunks,
        correlation_id=ctx.correlation_id,
        s3_client=s3_client,
    )
    ctx.metadata["final_object_key"] = final_result.asset.object_key
    ctx.metadata["final_asset_id"] = str(final_result.asset.id)
    ctx.metadata["final_skipped"] = final_result.skipped
    ctx.metadata["final_checksum_sha256"] = final_result.checksum_sha256


def mix_background(
    session: Session,
    audio_repo: AudioJobRepository,
    ctx: WorkflowContext,
    *,
    s3_client=None,
) -> None:
    """Mix a curated background bed under FINAL narration into the MASTER asset."""
    reload_job_and_chunks(session, audio_repo, ctx)
    assert ctx.job is not None

    master_result = finalize_audio_job_master(
        session,
        audio_repo,
        ctx.job,
        correlation_id=ctx.correlation_id,
        s3_client=s3_client,
    )
    ctx.metadata["master_object_key"] = master_result.asset.object_key
    ctx.metadata["master_asset_id"] = str(master_result.asset.id)
    ctx.metadata["master_skipped"] = master_result.skipped
    ctx.metadata["master_checksum_sha256"] = master_result.checksum_sha256


def finalize_manifest_only(
    session: Session,
    audio_repo: AudioJobRepository,
    ctx: WorkflowContext,
    *,
    s3_client=None,
) -> None:
    """Assemble the manifest referencing existing FINAL and MASTER assets."""
    reload_job_and_chunks(session, audio_repo, ctx)
    assert ctx.job is not None

    final_asset = audio_repo.find_final_asset(session, ctx.job.id)
    master_asset = audio_repo.find_master_asset(session, ctx.job.id)

    manifest_result = finalize_audio_job_manifest(
        session,
        audio_repo,
        ctx.job,
        ctx.chunks,
        correlation_id=ctx.correlation_id,
        s3_client=s3_client,
        final_asset=final_asset,
        master_asset=master_asset,
    )
    ctx.metadata["manifest_object_key"] = manifest_result.asset.object_key
    ctx.metadata["manifest_asset_id"] = str(manifest_result.asset.id)
    ctx.metadata["manifest_skipped"] = manifest_result.skipped
    ctx.metadata["manifest_checksum_sha256"] = manifest_result.manifest.checksum_sha256


def mark_completed(
    session: Session,
    audio_repo: AudioJobRepository,
    ctx: WorkflowContext,
) -> None:
    reload_job_and_chunks(session, audio_repo, ctx)
    assert ctx.job is not None

    pending = sum(
        1
        for chunk in ctx.chunks
        if chunk.status
        not in {AudioChunkStatus.COMPLETED, AudioChunkStatus.FAILED}
    )
    failed = sum(1 for chunk in ctx.chunks if chunk.status is AudioChunkStatus.FAILED)

    if pending > 0:
        raise WorkflowStateError(f"{pending} chunks are not completed")

    if audio_repo.find_master_asset(session, ctx.job.id) is None:
        raise WorkflowStateError("master asset required before job completion")

    if failed > 0:
        _resolve_job_failure(
            session,
            audio_repo,
            ctx,
            last_error=f"{failed} chunk(s) failed",
            partially_failed=True,
            increment_retry_count=False,
        )
        return

    audio_repo.mark_job_completed(session, ctx.audio_job_id, correlation_id=ctx.correlation_id)
    ctx.job = audio_repo.get_audio_job(session, ctx.audio_job_id)
    assert ctx.job is not None
    log_tts_job_completed(**tts_context_from_job(ctx.job, correlation_id=ctx.correlation_id))
    audio_repo.record_audio_event(
        session,
        ctx.audio_job_id,
        WORKFLOW_COMPLETED_EVENT,
        {"chunk_count": len(ctx.chunks)},
        correlation_id=ctx.correlation_id,
    )
    ctx.job = audio_repo.get_audio_job(session, ctx.audio_job_id)


def handle_failure(
    session: Session,
    audio_repo: AudioJobRepository,
    ctx: WorkflowContext,
    *,
    error: BaseException | None = None,
) -> None:
    if ctx.audio_job_id is None:
        return

    job = audio_repo.get_audio_job(session, ctx.audio_job_id)
    if job is None:
        return

    if job.status in {
        AudioJobStatus.COMPLETED,
        AudioJobStatus.FAILED,
        AudioJobStatus.PARTIALLY_FAILED,
        AudioJobStatus.REVIEW_REQUIRED,
    }:
        return

    error_message = ctx.last_error or "workflow failed"
    partially_failed = job.completed_chunks > 0
    reload_job_and_chunks(session, audio_repo, ctx)
    _resolve_job_failure(
        session,
        audio_repo,
        ctx,
        last_error=error_message,
        partially_failed=partially_failed,
        error=error,
    )
