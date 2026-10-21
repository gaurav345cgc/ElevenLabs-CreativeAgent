"""Phase 9 — chunk generation tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from models.enums import AudioChunkStatus, AudioJobStatus
from models.records import TranscriptAudioChunkRecord, TranscriptAudioJobRecord
from tts_pipeline.generator.chunk_generation import (
    build_chunk_synthesis_request,
    generate_chunks_sequentially,
    is_transient_generation_error,
    should_skip_chunk_generation,
    synthesize_chunk_with_retry,
)
from tts_pipeline.generator.elevenlabs_client import ElevenLabsApiError, SpeechSynthesisResult
from tts_pipeline.generator.elevenlabs_client import ElevenLabsSubscriptionSnapshot
from tts_pipeline.generator.chunk_synthesis import StoredChunkSynthesis
from tts_pipeline.persistence.s3_audio import StoredAudioObject


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
        "seed": 1337,
        "enable_logging": True,
        "created_at": now,
        "updated_at": now,
    }
    base.update(overrides)
    return TranscriptAudioJobRecord(**base)


def _chunk(job: TranscriptAudioJobRecord, index: int, text: str, **overrides) -> TranscriptAudioChunkRecord:
    now = datetime.now(UTC)
    data = {
        "id": uuid4(),
        "audio_job_id": job.id,
        "transcript_id": job.transcript_id,
        "transcript_version_id": job.transcript_version_id,
        "chunk_index": index,
        "status": AudioChunkStatus.PLANNED,
        "source_text": text,
        "previous_text": "Earlier context." if index > 0 else None,
        "next_text": "Later context." if index == 0 else None,
        "output_format": job.output_format,
        "mime_type": "audio/mpeg",
        "character_count": len(text),
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return TranscriptAudioChunkRecord(**data)


def test_should_skip_completed_chunk_with_object_key() -> None:
    job = _job()
    chunk = _chunk(
        job,
        0,
        "Done.",
        status=AudioChunkStatus.COMPLETED,
        output_object_key="tenant/transcript/job/chunks/0.mp3",
    )
    assert should_skip_chunk_generation(chunk) is True


def test_build_request_uses_text_continuity_for_first_pass() -> None:
    job = _job()
    chunks = [_chunk(job, 0, "Welcome.", next_text="Breathe.")]
    request = build_chunk_synthesis_request(job, chunks[0], chunks)
    assert request.previous_text is None
    assert request.next_text == "Breathe."
    assert request.previous_request_ids is None


def test_build_request_uses_request_ids_for_failed_chunk_regeneration() -> None:
    job = _job()
    chunks = [
        _chunk(
            job,
            0,
            "Welcome.",
            status=AudioChunkStatus.COMPLETED,
            eleven_request_id="req-0",
            output_object_key="key/0.mp3",
        ),
        _chunk(job, 1, "Middle.", status=AudioChunkStatus.FAILED),
        _chunk(
            job,
            2,
            "Closing.",
            status=AudioChunkStatus.COMPLETED,
            eleven_request_id="req-2",
            output_object_key="key/2.mp3",
        ),
    ]
    request = build_chunk_synthesis_request(job, chunks[1], chunks, regeneration=True)
    assert request.previous_request_ids == ["req-0"]
    assert request.next_request_ids == ["req-2"]
    assert request.previous_text is None
    assert request.next_text is None


def test_is_transient_generation_error() -> None:
    assert is_transient_generation_error(ElevenLabsApiError("x", status_code=503)) is True
    assert is_transient_generation_error(ElevenLabsApiError("x", status_code=402)) is False
    assert is_transient_generation_error(OSError("network")) is True


def test_synthesize_chunk_with_retry_on_transient_error(monkeypatch) -> None:
    calls = {"count": 0}

    def flaky_synthesize(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ElevenLabsApiError("down", status_code=503)
        return StoredChunkSynthesis(
            result=SpeechSynthesisResult.from_audio(b"x", response_headers={"request-id": "r1"}),
            stored=StoredAudioObject(
                bucket="b",
                object_key="k",
                checksum_sha256="c",
                byte_size=1,
                mime_type="audio/mpeg",
            ),
        )

    monkeypatch.setattr(
        "tts_pipeline.generator.chunk_generation.synthesize_and_store_chunk",
        flaky_synthesize,
    )
    monkeypatch.setattr("tts_pipeline.generator.chunk_generation.time.sleep", lambda *_: None)

    from tts_pipeline.generator.elevenlabs_client import SpeechSynthesisRequest

    stored = synthesize_chunk_with_retry(
        client=object(),
        request=SpeechSynthesisRequest(text="Hi.", voice_id="v"),
        tenant_id=uuid4(),
        transcript_id=uuid4(),
        audio_job_id=uuid4(),
        chunk_index=0,
    )
    assert stored.result.request_id == "r1"
    assert calls["count"] == 2


class FakeRepo:
    def __init__(self, job: TranscriptAudioJobRecord, chunks: list[TranscriptAudioChunkRecord]) -> None:
        self.job = job
        self.chunks = chunks
        self.events: list[str] = []
        self.marked_generating = False

    def mark_job_generating(self, session, audio_job_id, *, correlation_id=None):
        self.marked_generating = True
        return self.job

    def mark_chunk_generating(self, session, chunk_id):
        return next(c for c in self.chunks if c.id == chunk_id)

    def mark_chunk_completed(self, session, chunk_id, **kwargs):
        return next(c for c in self.chunks if c.id == chunk_id)

    def mark_chunk_failed(self, session, chunk_id, *, error_code, error_message):
        return next(c for c in self.chunks if c.id == chunk_id)

    def increment_job_chunk_counters(self, session, audio_job_id, *, completed_delta=0, failed_delta=0):
        self.job = self.job.model_copy(
            update={
                "completed_chunks": self.job.completed_chunks + completed_delta,
                "failed_chunks": self.job.failed_chunks + failed_delta,
            }
        )
        return self.job

    def record_audio_event(self, session, audio_job_id, event_type, payload, *, correlation_id=None):
        self.events.append(event_type)


class _UnlimitedCreditsClient:
    def get_subscription(self) -> ElevenLabsSubscriptionSnapshot:
        return ElevenLabsSubscriptionSnapshot(character_count=0, character_limit=10_000_000)


def test_generate_chunks_continues_after_one_failure(monkeypatch) -> None:
    job = _job()
    chunks = [
        _chunk(job, 0, "First chunk text here."),
        _chunk(job, 1, "Second chunk text here."),
    ]
    repo = FakeRepo(job, chunks)

    def fake_single(session, repo_arg, job_arg, chunk, all_chunks, client, *, correlation_id=None):
        if chunk.chunk_index == 0:
            repo_arg.mark_chunk_failed(session, chunk.id, error_code="Test", error_message="boom")
            repo_arg.increment_job_chunk_counters(session, job.id, failed_delta=1)
            repo_arg.record_audio_event(session, job.id, "CHUNK_FAILED", {}, correlation_id=correlation_id)
            return "failed"
        repo_arg.mark_chunk_completed(
            session,
            chunk.id,
            eleven_request_id="r1",
            output_object_key="k/1.mp3",
            checksum_sha256="abc",
            byte_size=10,
            response_headers_json={},
        )
        repo_arg.increment_job_chunk_counters(session, job.id, completed_delta=1)
        repo_arg.record_audio_event(session, job.id, "CHUNK_COMPLETED", {}, correlation_id=correlation_id)
        return "completed"

    monkeypatch.setattr(
        "tts_pipeline.generator.chunk_generation.generate_single_chunk",
        fake_single,
    )

    result = generate_chunks_sequentially(
        session=None,
        repo=repo,
        job=job,
        chunks=chunks,
        client=_UnlimitedCreditsClient(),
    )
    assert result.failed == 1
    assert result.completed == 1


def test_generate_chunks_skips_all_when_job_already_completed() -> None:
    job = _job(status=AudioJobStatus.COMPLETED)
    chunks = [
        _chunk(
            job,
            0,
            "Done.",
            status=AudioChunkStatus.COMPLETED,
            output_object_key="k/0.mp3",
        ),
        _chunk(
            job,
            1,
            "Also done.",
            status=AudioChunkStatus.COMPLETED,
            output_object_key="k/1.mp3",
        ),
    ]
    repo = FakeRepo(job, chunks)

    result = generate_chunks_sequentially(
        session=None,
        repo=repo,
        job=job,
        chunks=chunks,
        client=_UnlimitedCreditsClient(),
    )
    assert result.skipped == 2
    assert result.completed == 0
    assert result.failed == 0
    assert repo.marked_generating is False
    assert repo.events.count("CHUNK_SKIPPED") == 2
