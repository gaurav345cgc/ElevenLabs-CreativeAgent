"""Phase 8 — orchestrator tests."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from models.enums import AudioAssetKind, AudioChunkStatus, AudioJobStatus
from models.records import TranscriptAudioAssetRecord, TranscriptAudioChunkRecord, TranscriptAudioJobRecord
from tts_pipeline.finalizer.manifest import build_audio_job_manifest
from tts_pipeline.finalizer.service import (
    FinalAudioMergeError,
    FinalizeManifestResult,
    FinalizeMasterResult,
)
from tts_pipeline.generator.elevenlabs_client import ElevenLabsSubscriptionSnapshot, SpeechSynthesisResult
from tts_pipeline.orchestrator.context import WorkflowContext
from tts_pipeline.orchestrator.errors import WorkflowValidationError
from tts_pipeline.generator.chunk_generation import generate_chunks_sequentially
from tts_pipeline.orchestrator.states import finalize_manifest_only, mix_background, validate_input
from tts_pipeline.orchestrator.workflow import WorkflowInput, WorkflowResult, WorkflowState
from tts_pipeline.persistence.s3_audio import StoredAudioObject


@dataclass
class FakeStored:
    result: SpeechSynthesisResult
    stored: StoredAudioObject


class FakeElevenLabsClient:
    def get_subscription(self) -> ElevenLabsSubscriptionSnapshot:
        return ElevenLabsSubscriptionSnapshot(character_count=0, character_limit=10_000_000)


class FakeAudioRepo:
    def __init__(self, job: TranscriptAudioJobRecord, chunks: list[TranscriptAudioChunkRecord]) -> None:
        self.job = job
        self.chunks = chunks
        self.events: list[tuple[str, dict]] = []

    def mark_job_generating(self, session, audio_job_id, *, correlation_id=None):
        self.job = self.job.model_copy(update={"status": AudioJobStatus.GENERATING})
        return self.job

    def mark_chunk_generating(self, session, chunk_id):
        self.chunks = [
            chunk.model_copy(update={"status": AudioChunkStatus.GENERATING})
            if chunk.id == chunk_id
            else chunk
            for chunk in self.chunks
        ]
        return next(chunk for chunk in self.chunks if chunk.id == chunk_id)

    def mark_chunk_completed(self, session, chunk_id, **kwargs):
        self.chunks = [
            chunk.model_copy(
                update={
                    "status": AudioChunkStatus.COMPLETED,
                    "output_object_key": kwargs["output_object_key"],
                }
            )
            if chunk.id == chunk_id
            else chunk
            for chunk in self.chunks
        ]
        return next(chunk for chunk in self.chunks if chunk.id == chunk_id)

    def mark_chunk_failed(self, session, chunk_id, *, error_code, error_message):
        self.chunks = [
            chunk.model_copy(update={"status": AudioChunkStatus.FAILED})
            if chunk.id == chunk_id
            else chunk
            for chunk in self.chunks
        ]
        return next(chunk for chunk in self.chunks if chunk.id == chunk_id)

    def increment_job_chunk_counters(self, session, audio_job_id, *, completed_delta=0, failed_delta=0):
        self.job = self.job.model_copy(
            update={
                "completed_chunks": self.job.completed_chunks + completed_delta,
                "failed_chunks": self.job.failed_chunks + failed_delta,
            }
        )
        return self.job

    def record_audio_event(self, session, audio_job_id, event_type, payload, *, correlation_id=None):
        self.events.append((event_type, payload))


class OrchestratorWorkflowRepo(FakeAudioRepo):
    def __init__(
        self,
        job: TranscriptAudioJobRecord,
        chunks: list[TranscriptAudioChunkRecord],
        *,
        final_asset: TranscriptAudioAssetRecord | None = None,
        master_asset: TranscriptAudioAssetRecord | None = None,
    ) -> None:
        super().__init__(job, chunks)
        self.final_asset = final_asset
        self.master_asset = master_asset
        self.completed = False

    def get_audio_job(self, session, audio_job_id):
        return self.job

    def list_audio_chunks(self, session, audio_job_id):
        return self.chunks

    def find_final_asset(self, session, audio_job_id):
        return self.final_asset

    def find_master_asset(self, session, audio_job_id):
        return self.master_asset

    def mark_job_completed(self, session, audio_job_id, *, correlation_id=None):
        self.completed = True
        self.job = self.job.model_copy(update={"status": AudioJobStatus.COMPLETED})
        return self.job


POST_REGISTER_TRANSITIONS = (
    WorkflowState.REGISTER_ASSETS,
    WorkflowState.FINALIZE_FINAL,
    WorkflowState.MIX_BACKGROUND,
    WorkflowState.FINALIZE_MANIFEST,
    WorkflowState.MARK_COMPLETED,
)


def _asset(
    job: TranscriptAudioJobRecord,
    *,
    asset_kind: AudioAssetKind,
    object_key: str,
    checksum: str = "hash",
    byte_size: int = 100,
) -> TranscriptAudioAssetRecord:
    now = datetime.now(UTC)
    return TranscriptAudioAssetRecord(
        id=uuid4(),
        audio_job_id=job.id,
        asset_kind=asset_kind,
        object_key=object_key,
        mime_type="audio/mpeg",
        checksum=checksum,
        byte_size=byte_size,
        created_at=now,
    )


def _job(**overrides) -> TranscriptAudioJobRecord:
    now = datetime.now(UTC)
    base = {
        "id": uuid4(),
        "transcript_id": uuid4(),
        "transcript_version_id": uuid4(),
        "tenant_id": uuid4(),
        "idempotency_key": "test",
        "voice_profile_code": "drew_primary",
        "voice_id": "voice",
        "model_id": "eleven_multilingual_v2",
        "output_format": "mp3_44100_128",
        "status": AudioJobStatus.READY,
        "created_at": now,
        "updated_at": now,
    }
    base.update(overrides)
    return TranscriptAudioJobRecord(**base)


def _chunk(job: TranscriptAudioJobRecord, index: int, text: str) -> TranscriptAudioChunkRecord:
    now = datetime.now(UTC)
    return TranscriptAudioChunkRecord(
        id=uuid4(),
        audio_job_id=job.id,
        transcript_id=job.transcript_id,
        transcript_version_id=job.transcript_version_id,
        chunk_index=index,
        status=AudioChunkStatus.PLANNED,
        source_text=text,
        output_format=job.output_format,
        mime_type="audio/mpeg",
        character_count=len(text),
        created_at=now,
        updated_at=now,
    )


def test_workflow_state_order_includes_generation_before_completion() -> None:
    states = [
        WorkflowState.VALIDATE_INPUT,
        WorkflowState.CREATE_AUDIO_JOB,
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
    ]
    assert WorkflowState.GENERATE_CHUNKS_SEQUENTIALLY in states
    assert states.index(WorkflowState.PLAN_PAUSES) < states.index(WorkflowState.PLAN_CHUNKS)
    assert states.index(WorkflowState.PLAN_CHUNKS) < states.index(WorkflowState.MAP_PAUSES_TO_CHUNKS)
    assert states.index(WorkflowState.MAP_PAUSES_TO_CHUNKS) < states.index(
        WorkflowState.PERSIST_CHUNK_PLAN
    )
    assert states.index(WorkflowState.GENERATE_CHUNKS_SEQUENTIALLY) < states.index(
        WorkflowState.MARK_COMPLETED
    )
    assert states.index(WorkflowState.REGISTER_ASSETS) < states.index(WorkflowState.FINALIZE_FINAL)
    assert states.index(WorkflowState.FINALIZE_FINAL) < states.index(WorkflowState.MIX_BACKGROUND)
    assert states.index(WorkflowState.MIX_BACKGROUND) < states.index(WorkflowState.FINALIZE_MANIFEST)


def test_state_policies_include_pause_states() -> None:
    from tts_pipeline.orchestrator.config import STATE_POLICIES

    assert STATE_POLICIES["PlanPauses"].max_attempts == 3
    assert STATE_POLICIES["PlanPauses"].timeout_seconds == 60
    assert STATE_POLICIES["MapPausesToChunks"].max_attempts == 2
    assert STATE_POLICIES["MapPausesToChunks"].timeout_seconds == 30



def test_workflow_post_register_transition_order() -> None:
    for left, right in zip(POST_REGISTER_TRANSITIONS, POST_REGISTER_TRANSITIONS[1:], strict=False):
        assert POST_REGISTER_TRANSITIONS.index(left) < POST_REGISTER_TRANSITIONS.index(right)


def test_mix_background_state_calls_finalize_audio_job_master(monkeypatch) -> None:
    job = _job(status=AudioJobStatus.GENERATING)
    chunk = _chunk(job, 0, "Done.").model_copy(
        update={"status": AudioChunkStatus.COMPLETED, "output_object_key": "chunks/0.mp3"}
    )
    repo = OrchestratorWorkflowRepo(job, [chunk])
    ctx = WorkflowContext(correlation_id="corr", audio_job_id=job.id)
    master_calls: list[str] = []

    def fake_master(session, audio_repo, job, **kwargs):
        master_calls.append(str(job.id))
        master_asset = _asset(
            job,
            asset_kind=AudioAssetKind.MASTER,
            object_key=f"tenant/transcript/{job.id}/final/master.mp3",
            checksum="master-hash",
            byte_size=200,
        )
        return FinalizeMasterResult(
            stored=None,
            asset=master_asset,
            skipped=False,
            checksum_sha256="master-hash",
            byte_size=200,
        )

    monkeypatch.setattr("tts_pipeline.orchestrator.states.finalize_audio_job_master", fake_master)

    mix_background(None, repo, ctx)

    assert master_calls == [str(job.id)]
    assert ctx.metadata["master_object_key"].endswith("final/master.mp3")
    assert ctx.metadata["master_asset_id"]
    assert ctx.metadata["master_skipped"] is False


def test_finalize_manifest_only_state_skips_finalize_audio_job_final(monkeypatch) -> None:
    job = _job(status=AudioJobStatus.GENERATING)
    chunk = _chunk(job, 0, "Done.").model_copy(
        update={"status": AudioChunkStatus.COMPLETED, "output_object_key": "chunks/0.mp3"}
    )
    final_asset = _asset(
        job,
        asset_kind=AudioAssetKind.FINAL,
        object_key=f"tenant/transcript/{job.id}/final/final.mp3",
    )
    master_asset = _asset(
        job,
        asset_kind=AudioAssetKind.MASTER,
        object_key=f"tenant/transcript/{job.id}/final/master.mp3",
    )
    repo = OrchestratorWorkflowRepo(
        job,
        [chunk],
        final_asset=final_asset,
        master_asset=master_asset,
    )
    ctx = WorkflowContext(correlation_id="corr", audio_job_id=job.id)
    stitch_calls: list[str] = []
    manifest_calls: list[str] = []

    def fake_final(session, audio_repo, job, chunks, **kwargs):
        stitch_calls.append(str(job.id))

    def fake_manifest(session, audio_repo, job, chunks, **kwargs):
        manifest_calls.append(str(job.id))
        manifest = build_audio_job_manifest(job, chunks, correlation_id=kwargs.get("correlation_id"))
        manifest_asset = _asset(
            job,
            asset_kind=AudioAssetKind.MANIFEST,
            object_key=f"tenant/transcript/{job.id}/manifest/audio_manifest.json",
        )
        return FinalizeManifestResult(
            manifest=manifest,
            stored=None,
            asset=manifest_asset,
            skipped=False,
        )

    monkeypatch.setattr("tts_pipeline.orchestrator.states.finalize_audio_job_final", fake_final)
    monkeypatch.setattr("tts_pipeline.orchestrator.states.finalize_audio_job_manifest", fake_manifest)

    finalize_manifest_only(None, repo, ctx)

    assert stitch_calls == []
    assert manifest_calls == [str(job.id)]
    assert ctx.metadata["manifest_object_key"].endswith("audio_manifest.json")


def test_engine_replay_from_mix_background_runs_master_without_chunk_generation(monkeypatch) -> None:
    from tts_pipeline.orchestrator.engine import TtsWorkflowEngine

    job = _job(status=AudioJobStatus.GENERATING)
    chunk = _chunk(job, 0, "Done.").model_copy(
        update={"status": AudioChunkStatus.COMPLETED, "output_object_key": "chunks/0.mp3"}
    )
    final_asset = _asset(
        job,
        asset_kind=AudioAssetKind.FINAL,
        object_key=f"tenant/transcript/{job.id}/final/final.mp3",
    )
    repo = OrchestratorWorkflowRepo(job, [chunk], final_asset=final_asset)
    master_calls: list[str] = []
    manifest_calls: list[str] = []

    def fake_master(session, audio_repo, job, **kwargs):
        master_calls.append(str(job.id))
        master_asset = _asset(
            job,
            asset_kind=AudioAssetKind.MASTER,
            object_key=f"tenant/transcript/{job.id}/final/master.mp3",
        )
        repo.master_asset = master_asset
        return FinalizeMasterResult(
            stored=None,
            asset=master_asset,
            skipped=False,
            checksum_sha256="master-hash",
            byte_size=200,
        )

    def fake_manifest(session, audio_repo, job, chunks, **kwargs):
        manifest_calls.append(str(job.id))
        manifest = build_audio_job_manifest(job, chunks, correlation_id=kwargs.get("correlation_id"))
        manifest_asset = _asset(
            job,
            asset_kind=AudioAssetKind.MANIFEST,
            object_key=f"tenant/transcript/{job.id}/manifest/audio_manifest.json",
        )
        return FinalizeManifestResult(
            manifest=manifest,
            stored=None,
            asset=manifest_asset,
            skipped=False,
        )

    monkeypatch.setattr("tts_pipeline.orchestrator.states.finalize_audio_job_master", fake_master)
    monkeypatch.setattr("tts_pipeline.orchestrator.states.finalize_audio_job_manifest", fake_manifest)

    def forbid_generate(*_args, **_kwargs):
        raise AssertionError("chunk generation must not run during MIX_BACKGROUND replay")

    monkeypatch.setattr("tts_pipeline.orchestrator.engine.generate_chunks", forbid_generate)

    @contextmanager
    def fake_scope(*_args, **_kwargs):
        yield None

    monkeypatch.setattr("tts_pipeline.orchestrator.engine.tts_session_scope", fake_scope)

    engine = TtsWorkflowEngine(MagicMock())
    engine._audio_repo = repo

    result = engine.run(
        WorkflowInput(
            audio_job_id=job.id,
            start_state=WorkflowState.MIX_BACKGROUND,
            correlation_id="corr",
        )
    )

    assert isinstance(result, WorkflowResult)
    assert result.success is True
    assert result.final_state is WorkflowState.SUCCEEDED
    assert master_calls == [str(job.id)]
    assert manifest_calls == [str(job.id)]
    assert repo.completed is True


def test_engine_mix_failure_does_not_finalize_manifest_or_complete(monkeypatch) -> None:
    from tts_pipeline.orchestrator.engine import TtsWorkflowEngine

    job_id = uuid4()
    manifest_calls: list[str] = []
    completed_calls: list[str] = []

    @contextmanager
    def fake_scope(*_args, **_kwargs):
        yield MagicMock()

    def failing_mix(session, audio_repo, ctx, **kwargs):
        raise FinalAudioMergeError("background mix failed")

    def track_manifest(session, audio_repo, ctx, **kwargs):
        manifest_calls.append("manifest")

    def track_completed(session, audio_repo, ctx, **kwargs):
        completed_calls.append("completed")

    def fake_handle_failure(session, audio_repo, ctx, *, error=None):
        return None

    monkeypatch.setattr("tts_pipeline.orchestrator.engine.tts_session_scope", fake_scope)
    monkeypatch.setattr("tts_pipeline.orchestrator.engine.mix_background", failing_mix)
    monkeypatch.setattr("tts_pipeline.orchestrator.engine.finalize_manifest_only", track_manifest)
    monkeypatch.setattr("tts_pipeline.orchestrator.engine.mark_completed", track_completed)
    monkeypatch.setattr("tts_pipeline.orchestrator.engine.handle_failure", fake_handle_failure)

    engine = TtsWorkflowEngine(MagicMock())
    result = engine.run(
        WorkflowInput(
            audio_job_id=job_id,
            start_state=WorkflowState.MIX_BACKGROUND,
            correlation_id="corr",
        )
    )

    assert result.success is False
    assert manifest_calls == []
    assert completed_calls == []


def test_generate_chunks_sequentially_skips_completed(monkeypatch) -> None:
    job = _job()
    chunks = [
        _chunk(job, 0, "Already done."),
        _chunk(job, 1, "Generate me please."),
    ]
    chunks[0] = chunks[0].model_copy(
        update={
            "status": AudioChunkStatus.COMPLETED,
            "output_object_key": "key/0.mp3",
        }
    )
    repo = FakeAudioRepo(job, chunks)

    def fake_synthesize(client, request, **kwargs):
        return FakeStored(
            result=SpeechSynthesisResult.from_audio(b"mp3", response_headers={"request-id": "req-1"}),
            stored=StoredAudioObject(
                bucket="bucket",
                object_key=f"key/{kwargs['chunk_index']}.mp3",
                checksum_sha256="abc",
                byte_size=3,
                mime_type="audio/mpeg",
            ),
        )

    monkeypatch.setattr(
        "tts_pipeline.generator.chunk_generation.synthesize_and_store_chunk",
        fake_synthesize,
    )

    result = generate_chunks_sequentially(
        session=None,
        repo=repo,
        job=job,
        chunks=chunks,
        client=FakeElevenLabsClient(),
    )
    assert result.completed == 1
    assert result.failed == 0
    assert result.skipped == 1


def test_workflow_input_requires_job_id_for_mid_flow_start() -> None:
    with pytest.raises(WorkflowValidationError, match="Provide audio_job_id"):
        validate_input(
            WorkflowContext(correlation_id="test"),
            WorkflowInput(start_state=WorkflowState.GENERATE_CHUNKS_SEQUENTIALLY),
        )


def test_engine_pause_pipeline_session_transitions(monkeypatch) -> None:
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    from tts_pipeline.orchestrator.engine import TtsWorkflowEngine

    calls: list[str] = []

    @contextmanager
    def fake_scope(*_args, **_kwargs):
        yield MagicMock()

    def track(name: str):
        def _handler(*_args, **_kwargs):
            calls.append(name)

        return _handler

    monkeypatch.setattr("tts_pipeline.orchestrator.engine.tts_session_scope", fake_scope)
    monkeypatch.setattr(
        "tts_pipeline.orchestrator.engine.load_enhanced_transcript",
        track("load_enhanced_transcript"),
    )
    monkeypatch.setattr(
        "tts_pipeline.orchestrator.engine.plan_pauses",
        track("plan_pauses"),
    )
    monkeypatch.setattr(
        "tts_pipeline.orchestrator.engine.plan_and_persist_chunks",
        track("plan_and_persist_chunks"),
    )
    monkeypatch.setattr(
        "tts_pipeline.orchestrator.engine.map_pauses_to_chunks",
        track("map_pauses_to_chunks"),
    )
    monkeypatch.setattr(
        "tts_pipeline.orchestrator.engine.reload_job_and_chunks",
        lambda session, audio_repo, ctx: setattr(ctx, "chunks", [MagicMock()]),
    )

    engine = TtsWorkflowEngine(MagicMock())
    ctx = WorkflowContext(correlation_id="corr", audio_job_id=uuid4())

    transitions = [
        (WorkflowState.LOAD_ENHANCED_TRANSCRIPT, WorkflowState.PLAN_PAUSES),
        (WorkflowState.PLAN_PAUSES, WorkflowState.PLAN_CHUNKS),
        (WorkflowState.PLAN_CHUNKS, WorkflowState.MAP_PAUSES_TO_CHUNKS),
        (WorkflowState.MAP_PAUSES_TO_CHUNKS, WorkflowState.PERSIST_CHUNK_PLAN),
        (WorkflowState.PERSIST_CHUNK_PLAN, WorkflowState.GENERATE_CHUNKS_SEQUENTIALLY),
    ]
    for current, expected_next in transitions:
        assert engine._run_session_state(current, ctx) is expected_next

    assert calls == [
        "load_enhanced_transcript",
        "plan_pauses",
        "plan_and_persist_chunks",
        "map_pauses_to_chunks",
    ]


def test_engine_plan_pauses_failure_never_generates_chunks(monkeypatch) -> None:
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    from tts_pipeline.orchestrator.engine import TtsWorkflowEngine
    from tts_pipeline.pause_planner.errors import PausePlannerValidationError

    generate_calls: list[str] = []

    @contextmanager
    def fake_scope(*_args, **_kwargs):
        yield MagicMock()

    def failing_plan_pauses(*_args, **_kwargs):
        raise PausePlannerValidationError("planner returned invalid JSON")

    def track_generate(*_args, **_kwargs):
        generate_calls.append("generate")

    def fake_handle_failure(session, audio_repo, ctx, *, error=None):
        return None

    monkeypatch.setattr("tts_pipeline.orchestrator.engine.tts_session_scope", fake_scope)
    monkeypatch.setattr("tts_pipeline.orchestrator.engine.plan_pauses", failing_plan_pauses)
    monkeypatch.setattr("tts_pipeline.orchestrator.engine.generate_chunks", track_generate)
    monkeypatch.setattr("tts_pipeline.orchestrator.engine.handle_failure", fake_handle_failure)
    monkeypatch.setattr(
        "tts_pipeline.orchestrator.engine.plan_and_persist_chunks",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("PlanChunks must not run after PlanPauses failure")
        ),
    )

    engine = TtsWorkflowEngine(MagicMock())
    result = engine.run(
        WorkflowInput(
            audio_job_id=uuid4(),
            start_state=WorkflowState.PLAN_PAUSES,
            correlation_id="corr",
        )
    )

    assert result.success is False
    assert result.final_state is WorkflowState.FAILURE_HANDLER
    assert generate_calls == []
    assert "invalid JSON" in (result.error or "")


def test_engine_plan_pauses_retries_transient_then_succeeds(monkeypatch) -> None:
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    from tts_pipeline.orchestrator.engine import TtsWorkflowEngine
    from tts_pipeline.pause_planner.errors import PausePlannerTransientError

    attempts = {"n": 0}

    @contextmanager
    def fake_scope(*_args, **_kwargs):
        yield MagicMock()

    def flaky_plan_pauses(*_args, **_kwargs):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise PausePlannerTransientError("openai 503")

    monkeypatch.setattr("tts_pipeline.orchestrator.engine.tts_session_scope", fake_scope)
    monkeypatch.setattr("tts_pipeline.orchestrator.engine.plan_pauses", flaky_plan_pauses)

    engine = TtsWorkflowEngine(MagicMock())
    ctx = WorkflowContext(correlation_id="corr", audio_job_id=uuid4())
    assert engine._run_session_state(WorkflowState.PLAN_PAUSES, ctx) is WorkflowState.PLAN_CHUNKS
    assert attempts["n"] == 3

    from contextlib import contextmanager
    from unittest.mock import MagicMock

    from tts_pipeline.orchestrator.engine import TtsWorkflowEngine

    calls: list[str] = []

    @contextmanager
    def fake_scope(*_args, **_kwargs):
        yield MagicMock()

    def track(name: str):
        def _handler(session, audio_repo, ctx, **kwargs):
            calls.append(name)

        return _handler

    monkeypatch.setattr("tts_pipeline.orchestrator.engine.tts_session_scope", fake_scope)
    monkeypatch.setattr(
        "tts_pipeline.orchestrator.engine.register_assets",
        track("register_assets"),
    )
    monkeypatch.setattr(
        "tts_pipeline.orchestrator.engine.finalize_final",
        track("finalize_final"),
    )
    monkeypatch.setattr(
        "tts_pipeline.orchestrator.engine.mix_background",
        track("mix_background"),
    )
    monkeypatch.setattr(
        "tts_pipeline.orchestrator.engine.finalize_manifest_only",
        track("finalize_manifest_only"),
    )
    monkeypatch.setattr(
        "tts_pipeline.orchestrator.engine.mark_completed",
        track("mark_completed"),
    )

    engine = TtsWorkflowEngine(MagicMock())
    ctx = WorkflowContext(correlation_id="corr", audio_job_id=uuid4())

    transitions = [
        (WorkflowState.REGISTER_ASSETS, WorkflowState.FINALIZE_FINAL),
        (WorkflowState.FINALIZE_FINAL, WorkflowState.MIX_BACKGROUND),
        (WorkflowState.MIX_BACKGROUND, WorkflowState.FINALIZE_MANIFEST),
        (WorkflowState.FINALIZE_MANIFEST, WorkflowState.MARK_COMPLETED),
        (WorkflowState.MARK_COMPLETED, WorkflowState.SUCCEEDED),
    ]
    for current, expected_next in transitions:
        assert engine._run_session_state(current, ctx) is expected_next

    assert calls == [
        "register_assets",
        "finalize_final",
        "mix_background",
        "finalize_manifest_only",
        "mark_completed",
    ]


def test_engine_mix_background_failure_returns_unsuccessful_result(monkeypatch) -> None:
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    from tts_pipeline.finalizer import FinalAudioMergeError
    from tts_pipeline.orchestrator.engine import TtsWorkflowEngine
    from tts_pipeline.orchestrator.workflow import WorkflowInput, WorkflowResult

    job_id = uuid4()

    @contextmanager
    def fake_scope(*_args, **_kwargs):
        yield MagicMock()

    def failing_mix(session, audio_repo, ctx, **kwargs):
        raise FinalAudioMergeError("background mix failed")

    def fake_handle_failure(session, audio_repo, ctx, *, error=None):
        return None

    monkeypatch.setattr("tts_pipeline.orchestrator.engine.tts_session_scope", fake_scope)
    monkeypatch.setattr("tts_pipeline.orchestrator.engine.mix_background", failing_mix)
    monkeypatch.setattr("tts_pipeline.orchestrator.engine.handle_failure", fake_handle_failure)

    engine = TtsWorkflowEngine(MagicMock())
    result = engine.run(
        WorkflowInput(
            audio_job_id=job_id,
            start_state=WorkflowState.MIX_BACKGROUND,
            correlation_id="corr",
        )
    )

    assert isinstance(result, WorkflowResult)
    assert result.success is False
    assert result.audio_job_id == job_id
    assert result.error is not None
    assert "background mix failed" in result.error


def test_mark_completed_requires_master_asset() -> None:
    from tts_pipeline.orchestrator.errors import WorkflowStateError
    from tts_pipeline.orchestrator.states import mark_completed

    job = _job(status=AudioJobStatus.GENERATING)
    chunk = _chunk(job, 0, "Done.")
    chunk = chunk.model_copy(update={"status": AudioChunkStatus.COMPLETED})

    class CompletionRepo(FakeAudioRepo):
        def get_audio_job(self, session, audio_job_id):
            return self.job

        def list_audio_chunks(self, session, audio_job_id):
            return self.chunks

        def find_master_asset(self, session, audio_job_id):
            return None

        def mark_job_completed(self, session, audio_job_id, *, correlation_id=None):
            raise AssertionError("must not complete without master asset")

    repo = CompletionRepo(job, [chunk])
    ctx = WorkflowContext(correlation_id="corr", audio_job_id=job.id, job=job, chunks=[chunk])

    with pytest.raises(WorkflowStateError, match="master asset required"):
        mark_completed(None, repo, ctx)
