"""Phase 12: PlanPauses / MapPausesToChunks workflow handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from models.enums import AudioChunkStatus, AudioJobStatus, VersionKind
from models.records import TranscriptAudioChunkRecord, TranscriptAudioJobRecord, TranscriptVersionRecord
from tts_pipeline.orchestrator.context import WorkflowContext
from tts_pipeline.orchestrator.errors import WorkflowStateError
from tts_pipeline.orchestrator.states import map_pauses_to_chunks, plan_pauses
from tts_pipeline.orchestrator.workflow import WorkflowState
from tts_pipeline.pause_planner.policy import PAUSE_POLICY_VERSION, PROMPT_VERSION
from tts_pipeline.pause_planner.schema import (
    PauseHold,
    PauseHoldKind,
    PausePlan,
    PausePlannerProvider,
)
from tts_pipeline.pause_planner.service import (
    MAPPED_PAUSE_PLAN_KEY,
    PAUSE_PLAN_KEY,
    PAUSE_PLAN_VERSIONS_KEY,
)


class FakeAudioRepo:
    def __init__(self, job: TranscriptAudioJobRecord, chunks: list[TranscriptAudioChunkRecord]) -> None:
        self.job = job
        self.chunks = list(chunks)
        self.events: list[tuple[str, dict | None]] = []

    def get_audio_job(self, session, audio_job_id):
        assert audio_job_id == self.job.id
        return self.job

    def list_audio_chunks(self, session, audio_job_id):
        assert audio_job_id == self.job.id
        return list(self.chunks)

    def merge_audio_job_metadata(self, session, audio_job_id, patch, *, correlation_id=None):
        assert audio_job_id == self.job.id
        self.job = self.job.model_copy(
            update={"metadata_json": {**(self.job.metadata_json or {}), **patch}}
        )
        return self.job

    def record_audio_event(self, session, audio_job_id, event_type, payload=None, *, correlation_id=None):
        self.events.append((event_type, payload))


class FakeTranscriptRepo:
    def __init__(self, version: TranscriptVersionRecord) -> None:
        self.version = version

    def get_transcript_version(self, session, transcript_id, version_id):
        assert transcript_id == self.version.transcript_id
        assert version_id == self.version.id
        return self.version


def _version(*, beats: list[str] | None = None, content_text: str = "Hello.\n\nWorld.") -> TranscriptVersionRecord:
    return TranscriptVersionRecord(
        id=uuid4(),
        transcript_id=uuid4(),
        version_kind=VersionKind.ELEVENLABS_ENHANCED,
        content_text=content_text,
        created_by_agent="test",
        metadata_json={},
        created_at=datetime.now(UTC),
        content_json={"beats": beats} if beats is not None else None,
    )


def _job(version: TranscriptVersionRecord, *, metadata: dict | None = None) -> TranscriptAudioJobRecord:
    now = datetime.now(UTC)
    return TranscriptAudioJobRecord(
        id=uuid4(),
        transcript_id=version.transcript_id,
        transcript_version_id=version.id,
        tenant_id=uuid4(),
        idempotency_key=f"idem-{uuid4()}",
        voice_id="voice",
        model_id="model",
        output_format="mp3_44100_128",
        status=AudioJobStatus.PLANNING,
        created_at=now,
        updated_at=now,
        metadata_json=dict(metadata or {}),
    )


def _chunk(job: TranscriptAudioJobRecord, *, index: int, text: str) -> TranscriptAudioChunkRecord:
    now = datetime.now(UTC)
    return TranscriptAudioChunkRecord(
        id=uuid4(),
        audio_job_id=job.id,
        transcript_id=job.transcript_id,
        transcript_version_id=job.transcript_version_id,
        chunk_index=index,
        status=AudioChunkStatus.PLANNED,
        source_text=text,
        output_format="mp3_44100_128",
        mime_type="audio/mpeg",
        character_count=len(text),
        created_at=now,
        updated_at=now,
        estimated_duration_ms=1000,
        metadata_json={"boundary_source": "paragraphs"},
    )


def _plan(*, after_beat: int = 0, seconds: int = 12) -> PausePlan:
    return PausePlan(
        planner=PausePlannerProvider.OPENAI,
        model="gpt-4o-mini",
        prompt_version=PROMPT_VERSION,
        policy_version=PAUSE_POLICY_VERSION,
        target_duration_seconds=600,
        estimated_speech_seconds=30,
        total_hold_seconds=seconds,
        holds=[
            PauseHold(
                hold_id="h1",
                after_beat_index=after_beat,
                hold_seconds=seconds,
                kind=PauseHoldKind.PRACTICE,
                reason="absorb cue",
            )
        ],
    )


def test_workflow_state_enum_includes_pause_states() -> None:
    assert WorkflowState.PLAN_PAUSES.value == "PlanPauses"
    assert WorkflowState.MAP_PAUSES_TO_CHUNKS.value == "MapPausesToChunks"


def test_plan_pauses_creates_plan_via_factory() -> None:
    version = _version(beats=["Soften shoulders.", "Return gently."])
    job = _job(version, metadata={"target_duration_seconds": 600})
    repo = FakeAudioRepo(job, [])
    transcript_repo = FakeTranscriptRepo(version)
    ctx = WorkflowContext(correlation_id="c1", audio_job_id=job.id, job=job)
    calls = {"n": 0}

    def factory() -> PausePlan:
        calls["n"] += 1
        return _plan(seconds=12)

    plan_pauses(None, repo, transcript_repo, ctx, plan_factory=factory)

    assert calls["n"] == 1
    assert ctx.metadata["pause_plan_created"] is True
    assert ctx.metadata["pause_plan_reused"] is False
    assert ctx.metadata["pause_plan_hold_count"] == 1
    assert ctx.metadata["pause_plan_total_hold_seconds"] == 12
    assert ctx.metadata["pause_anchors_preferred"] == "beats"
    assert PAUSE_PLAN_KEY in (ctx.job.metadata_json or {})
    assert PAUSE_PLAN_VERSIONS_KEY in (ctx.job.metadata_json or {})


def test_plan_pauses_reuses_existing_plan_without_factory() -> None:
    version = _version(beats=["Cue one.", "Cue two."])
    existing = _plan(seconds=15)
    job = _job(
        version,
        metadata={
            PAUSE_PLAN_KEY: existing.model_dump(mode="json"),
            PAUSE_PLAN_VERSIONS_KEY: {
                "policy_version": PAUSE_POLICY_VERSION,
                "prompt_version": PROMPT_VERSION,
                "model": "gpt-4o-mini",
            },
        },
    )
    repo = FakeAudioRepo(job, [])
    transcript_repo = FakeTranscriptRepo(version)
    ctx = WorkflowContext(correlation_id="c1", audio_job_id=job.id, job=job)

    plan_pauses(
        None,
        repo,
        transcript_repo,
        ctx,
        plan_factory=lambda: (_ for _ in ()).throw(AssertionError("OpenAI must not be called")),
    )

    assert ctx.metadata["pause_plan_reused"] is True
    assert ctx.metadata["pause_plan_created"] is False
    assert ctx.metadata["pause_plan_hold_count"] == 1
    assert ctx.job.metadata_json[PAUSE_PLAN_KEY]["holds"][0]["hold_seconds"] == 15


def test_map_pauses_to_chunks_persists_mapped_plan_without_openai() -> None:
    version = _version(beats=["Soften shoulders.", "Return gently."])
    existing = _plan(after_beat=0, seconds=12)
    job = _job(
        version,
        metadata={
            PAUSE_PLAN_KEY: existing.model_dump(mode="json"),
            "boundary_source": "paragraphs",
        },
    )
    chunks = [
        _chunk(job, index=0, text="Soften shoulders."),
        _chunk(job, index=1, text="Return gently."),
    ]
    repo = FakeAudioRepo(job, chunks)
    transcript_repo = FakeTranscriptRepo(version)
    ctx = WorkflowContext(
        correlation_id="c1",
        audio_job_id=job.id,
        job=job,
        chunks=chunks,
        transcript_version=version,
    )

    map_pauses_to_chunks(None, repo, transcript_repo, ctx)

    assert MAPPED_PAUSE_PLAN_KEY in (ctx.job.metadata_json or {})
    assert ctx.metadata["mapped_pause_hold_count"] == 1
    assert ctx.metadata["mapped_pause_total_hold_seconds"] == 12
    assert ctx.metadata["mapped_pause_after_chunk_indexes"] == [0]
    assert any(event_type == "PAUSE_PLAN_MAPPED" for event_type, _ in repo.events)


def test_map_pauses_to_chunks_requires_pause_plan() -> None:
    version = _version(beats=["Only cue."])
    job = _job(version)
    chunk = _chunk(job, index=0, text="Only cue.")
    repo = FakeAudioRepo(job, [chunk])
    transcript_repo = FakeTranscriptRepo(version)
    ctx = WorkflowContext(correlation_id="c1", audio_job_id=job.id, job=job, chunks=[chunk])

    with pytest.raises(WorkflowStateError, match="missing pause_plan"):
        map_pauses_to_chunks(None, repo, transcript_repo, ctx)


def test_map_pauses_to_chunks_requires_chunks() -> None:
    version = _version(beats=["Only cue."])
    existing = _plan(seconds=8)
    job = _job(version, metadata={PAUSE_PLAN_KEY: existing.model_dump(mode="json")})
    repo = FakeAudioRepo(job, [])
    transcript_repo = FakeTranscriptRepo(version)
    ctx = WorkflowContext(correlation_id="c1", audio_job_id=job.id, job=job, chunks=[])

    with pytest.raises(WorkflowStateError, match="no planned chunks"):
        map_pauses_to_chunks(None, repo, transcript_repo, ctx)
