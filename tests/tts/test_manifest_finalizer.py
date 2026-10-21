"""Phase 11 — manifest assembly and finalization tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from models.enums import AudioAssetKind, AudioChunkStatus, AudioJobStatus
from models.records import TranscriptAudioAssetRecord, TranscriptAudioChunkRecord, TranscriptAudioJobRecord
from tts_pipeline.finalizer.manifest import build_audio_job_manifest
from tts_pipeline.finalizer.service import (
    FinalAudioMergeError,
    finalize_audio_job_final,
    finalize_audio_job_manifest,
    finalize_audio_job_master,
)
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
        "voice_id": "voice-123",
        "model_id": "eleven_multilingual_v2",
        "output_format": "mp3_44100_128",
        "status": AudioJobStatus.GENERATING,
        "created_at": now,
        "updated_at": now,
    }
    base.update(overrides)
    return TranscriptAudioJobRecord(**base)


def _chunk(job: TranscriptAudioJobRecord, index: int, **overrides) -> TranscriptAudioChunkRecord:
    now = datetime.now(UTC)
    data = {
        "id": uuid4(),
        "audio_job_id": job.id,
        "transcript_id": job.transcript_id,
        "transcript_version_id": job.transcript_version_id,
        "chunk_index": index,
        "status": AudioChunkStatus.COMPLETED,
        "source_text": "Hello there.",
        "output_format": job.output_format,
        "mime_type": "audio/mpeg",
        "character_count": 12,
        "eleven_request_id": f"req-{index}",
        "output_object_key": f"tenant/transcript/{job.id}/chunks/{index}.mp3",
        "estimated_duration_ms": 1000 + index,
        "metadata_json": {"byte_size": 100, "checksum_sha256": f"hash-{index}"},
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return TranscriptAudioChunkRecord(**data)


def test_build_audio_job_manifest_includes_required_fields() -> None:
    job = _job()
    chunks = [_chunk(job, 0), _chunk(job, 1)]
    manifest = build_audio_job_manifest(job, chunks, correlation_id="corr-1")

    payload = manifest.to_dict()
    assert payload["transcript_id"] == str(job.transcript_id)
    assert payload["transcript_version_id"] == str(job.transcript_version_id)
    assert payload["audio_job_id"] == str(job.id)
    assert payload["voice_id"] == job.voice_id
    assert payload["model_id"] == job.model_id
    assert payload["output_format"] == job.output_format
    assert payload["status"] == job.status.value
    assert payload["chunk_count"] == 2
    assert payload["total_duration_ms"] == 2001
    assert len(payload["chunks"]) == 2
    assert payload["chunks"][0]["request_id"] == "req-0"
    assert payload["chunks"][0]["object_key"].endswith("/0.mp3")
    assert payload["chunks"][0]["duration_ms"] == 1000
    assert payload["correlation_id"] == "corr-1"


class FakeRepo:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self.manifest_assets: dict[str, TranscriptAudioAssetRecord] = {}
        self.final_assets: dict[str, TranscriptAudioAssetRecord] = {}
        self.master_assets: dict[str, TranscriptAudioAssetRecord] = {}
        self.job_final_asset_ids: dict[str, UUID] = {}

    def find_manifest_asset(self, session, audio_job_id):
        return self.manifest_assets.get(str(audio_job_id))

    def find_final_asset(self, session, audio_job_id):
        return self.final_assets.get(str(audio_job_id))

    def find_master_asset(self, session, audio_job_id):
        return self.master_assets.get(str(audio_job_id))

    def create_audio_asset(self, session, data, *, correlation_id=None):
        now = datetime.now(UTC)
        asset = TranscriptAudioAssetRecord(
            id=uuid4(),
            audio_job_id=data.audio_job_id,
            asset_kind=data.asset_kind,
            object_key=data.object_key,
            mime_type=data.mime_type,
            checksum=data.checksum,
            byte_size=data.byte_size,
            metadata_json=data.metadata_json,
            created_at=now,
        )
        if data.asset_kind is AudioAssetKind.MANIFEST:
            self.manifest_assets[str(data.audio_job_id)] = asset
        elif data.asset_kind is AudioAssetKind.FINAL:
            self.final_assets[str(data.audio_job_id)] = asset
        elif data.asset_kind is AudioAssetKind.MASTER:
            self.master_assets[str(data.audio_job_id)] = asset
        return asset

    def update_audio_asset(self, session, asset_id, *, checksum=None, byte_size=None, metadata_json=None, correlation_id=None):
        for store in (self.manifest_assets, self.final_assets):
            for key, asset in store.items():
                if asset.id == asset_id:
                    updated = asset.model_copy(
                        update={
                            "checksum": checksum if checksum is not None else asset.checksum,
                            "byte_size": byte_size if byte_size is not None else asset.byte_size,
                            "metadata_json": metadata_json if metadata_json is not None else asset.metadata_json,
                        }
                    )
                    store[key] = updated
                    return updated
        raise ValueError(f"asset {asset_id} not found")

    def set_job_final_asset_id(self, session, audio_job_id, final_asset_id, *, correlation_id=None):
        self.job_final_asset_ids[str(audio_job_id)] = final_asset_id
        return None

    def record_audio_event(self, session, audio_job_id, event_type, payload, *, correlation_id=None):
        self.events.append((event_type, payload))


def test_finalize_audio_job_manifest_writes_s3_and_registers_asset(monkeypatch) -> None:
    job = _job()
    chunks = [_chunk(job, 0)]
    repo = FakeRepo()

    monkeypatch.setattr(
        "tts_pipeline.finalizer.service.write_json_object",
        lambda **kwargs: StoredAudioObject(
            bucket="bucket",
            object_key=kwargs["object_key"],
            byte_size=len(kwargs["payload"]),
            checksum_sha256=kwargs["checksum_sha256"],
            mime_type="application/json",
        ),
    )

    result = finalize_audio_job_manifest(None, repo, job, chunks, correlation_id="corr-2")

    assert result.skipped is False
    assert result.stored is not None
    assert result.asset.asset_kind is AudioAssetKind.MANIFEST
    assert result.asset.object_key.endswith("manifest/audio_manifest.json")
    assert any(event[0] == "MANIFEST_FINALIZED" for event in repo.events)


def test_finalize_skips_when_completed_job_already_has_manifest() -> None:
    job = _job(status=AudioJobStatus.COMPLETED)
    chunks = [_chunk(job, 0)]
    repo = FakeRepo()
    now = datetime.now(UTC)
    existing = TranscriptAudioAssetRecord(
        id=uuid4(),
        audio_job_id=job.id,
        asset_kind=AudioAssetKind.MANIFEST,
        object_key="existing/manifest/audio_manifest.json",
        mime_type="application/json",
        created_at=now,
    )
    repo.manifest_assets[str(job.id)] = existing

    result = finalize_audio_job_manifest(None, repo, job, chunks)

    assert result.skipped is True
    assert result.stored is None
    assert result.asset.id == existing.id
    assert any(event[0] == "MANIFEST_SKIPPED" for event in repo.events)


def test_finalize_audio_job_final_merges_uploads_and_sets_final_asset(monkeypatch) -> None:
    job = _job()
    chunks = [_chunk(job, 0), _chunk(job, 1)]
    repo = FakeRepo()
    downloaded: list[str] = []

    def fake_read_object_bytes(*, object_key, s3_client=None):
        downloaded.append(object_key)
        return b"chunk-bytes"

    def fake_merge(chunk_bytes):
        assert len(chunk_bytes) == 2
        return b"merged-final-mp3"

    monkeypatch.setattr(
        "tts_pipeline.finalizer.service.read_object_bytes",
        fake_read_object_bytes,
    )
    monkeypatch.setattr(
        "tts_pipeline.finalizer.service.write_audio_object",
        lambda **kwargs: StoredAudioObject(
            bucket="bucket",
            object_key=kwargs["object_key"],
            byte_size=len(kwargs["audio_bytes"]),
            checksum_sha256=kwargs["checksum_sha256"],
            mime_type=kwargs["mime_type"],
        ),
    )

    result = finalize_audio_job_final(
        None,
        repo,
        job,
        chunks,
        merge_fn=fake_merge,
    )

    assert result.skipped is False
    assert result.byte_size == len(b"merged-final-mp3")
    assert result.asset.asset_kind is AudioAssetKind.FINAL
    assert result.asset.object_key.endswith("final/final.mp3")
    assert repo.job_final_asset_ids[str(job.id)] == result.asset.id
    assert len(downloaded) == 2
    assert any(event[0] == "FINAL_MERGED" for event in repo.events)


def test_finalize_audio_job_final_uses_mapped_pause_holds(monkeypatch) -> None:
    job = _job(
        metadata_json={
            "mapped_pause_plan": {
                "schema_version": "1.0",
                "total_hold_seconds": 17,
                "holds": [
                    {
                        "hold_id": "h1",
                        "after_beat_index": 0,
                        "after_chunk_index": 0,
                        "hold_seconds": 12,
                        "kind": "practice",
                        "reason": "absorb",
                    },
                    {
                        "hold_id": "h2",
                        "after_beat_index": 1,
                        "after_chunk_index": 1,
                        "hold_seconds": 5,
                        "kind": "section",
                        "reason": "rest",
                    },
                ],
            }
        }
    )
    chunks = [_chunk(job, 0), _chunk(job, 1)]
    repo = FakeRepo()
    seen_holds: list[tuple[int, int]] = []

    def fake_read_object_bytes(*, object_key, s3_client=None):
        return b"chunk-bytes"

    def fake_merge_with_holds(chunk_bytes, holds):
        assert len(chunk_bytes) == 2
        seen_holds.extend(holds)
        return b"merged-with-holds"

    monkeypatch.setattr(
        "tts_pipeline.finalizer.service.read_object_bytes",
        fake_read_object_bytes,
    )
    monkeypatch.setattr(
        "tts_pipeline.finalizer.service.write_audio_object",
        lambda **kwargs: StoredAudioObject(
            bucket="bucket",
            object_key=kwargs["object_key"],
            byte_size=len(kwargs["audio_bytes"]),
            checksum_sha256=kwargs["checksum_sha256"],
            mime_type=kwargs["mime_type"],
        ),
    )

    result = finalize_audio_job_final(
        None,
        repo,
        job,
        chunks,
        merge_with_holds_fn=fake_merge_with_holds,
    )

    assert result.skipped is False
    assert seen_holds == [(0, 12), (1, 5)]
    assert result.asset.metadata_json["hold_count"] == 2
    assert result.asset.metadata_json["total_hold_seconds"] == 17
    assert result.asset.metadata_json["merge_strategy"] == "ffmpeg_concat_reencode_with_holds"
    merged_events = [payload for event_type, payload in repo.events if event_type == "FINAL_MERGED"]
    assert merged_events
    assert merged_events[0]["hold_count"] == 2
    assert merged_events[0]["total_hold_seconds"] == 17


def test_finalize_manifest_includes_final_asset_fields(monkeypatch) -> None:
    job = _job()
    chunks = [_chunk(job, 0)]
    repo = FakeRepo()
    now = datetime.now(UTC)
    final_asset = TranscriptAudioAssetRecord(
        id=uuid4(),
        audio_job_id=job.id,
        asset_kind=AudioAssetKind.FINAL,
        object_key=f"tenant/transcript/{job.id}/final/final.mp3",
        mime_type="audio/mpeg",
        checksum="final-hash",
        byte_size=999,
        created_at=now,
    )
    repo.final_assets[str(job.id)] = final_asset

    monkeypatch.setattr(
        "tts_pipeline.finalizer.service.write_json_object",
        lambda **kwargs: StoredAudioObject(
            bucket="bucket",
            object_key=kwargs["object_key"],
            byte_size=len(kwargs["payload"]),
            checksum_sha256=kwargs["checksum_sha256"],
            mime_type="application/json",
        ),
    )

    result = finalize_audio_job_manifest(
        None,
        repo,
        job,
        chunks,
        final_asset=final_asset,
    )

    payload = result.manifest.to_dict()
    assert payload["final_object_key"] == final_asset.object_key
    assert payload["final_asset_id"] == str(final_asset.id)
    assert payload["final_checksum_sha256"] == "final-hash"
    assert payload["final_byte_size"] == 999


def _register_final_asset(repo: FakeRepo, job: TranscriptAudioJobRecord) -> TranscriptAudioAssetRecord:
    now = datetime.now(UTC)
    final_asset = TranscriptAudioAssetRecord(
        id=uuid4(),
        audio_job_id=job.id,
        asset_kind=AudioAssetKind.FINAL,
        object_key=f"tenant/transcript/{job.id}/final/final.mp3",
        mime_type="audio/mpeg",
        checksum="final-hash",
        byte_size=999,
        created_at=now,
    )
    repo.final_assets[str(job.id)] = final_asset
    return final_asset


def test_finalize_audio_job_master_mixes_and_registers_asset(monkeypatch) -> None:
    job = _job()
    repo = FakeRepo()
    final_asset = _register_final_asset(repo, job)
    reads: list[str] = []

    def fake_read_object_bytes(*, object_key, s3_client=None):
        reads.append(object_key)
        return b"narration" if object_key == final_asset.object_key else b"bed"

    monkeypatch.setattr(
        "tts_pipeline.finalizer.service.read_object_bytes",
        fake_read_object_bytes,
    )
    monkeypatch.setattr(
        "tts_pipeline.finalizer.service.write_audio_object",
        lambda **kwargs: StoredAudioObject(
            bucket="bucket",
            object_key=kwargs["object_key"],
            byte_size=len(kwargs["audio_bytes"]),
            checksum_sha256=kwargs["checksum_sha256"],
            mime_type=kwargs["mime_type"],
        ),
    )

    def fake_mix(narration_bytes, bed_bytes, profile):
        assert narration_bytes == b"narration"
        assert bed_bytes == b"bed"
        return b"master-mp3-bytes"

    result = finalize_audio_job_master(None, repo, job, mix_fn=fake_mix)

    assert result.skipped is False
    assert result.byte_size == len(b"master-mp3-bytes")
    assert result.asset.asset_kind is AudioAssetKind.MASTER
    assert result.asset.object_key.endswith("final/master.mp3")
    assert result.asset.metadata_json["background_profile_code"] == "calm_ambient_01"
    assert result.asset.metadata_json["source_final_asset_id"] == str(final_asset.id)
    assert result.asset.metadata_json["merge_strategy"] == "ffmpeg_amix"
    # narration read before bed
    assert reads == [final_asset.object_key, "background/calm_ambient_01.mp3"]
    assert any(event[0] == "MASTER_MIXED" for event in repo.events)
    # final_asset_id must remain FINAL, not repurposed to MASTER
    assert str(job.id) not in repo.job_final_asset_ids


def test_finalize_audio_job_master_reads_and_passes_chime_bytes(monkeypatch) -> None:
    import dataclasses

    from tts_pipeline.background_policy import get_background_profile

    job = _job()
    repo = FakeRepo()
    final_asset = _register_final_asset(repo, job)

    chime_profile = dataclasses.replace(
        get_background_profile("calm_ambient_01"),
        intro_chime_object_key="chimes/intro.mp3",
        outro_chime_object_key="chimes/outro.mp3",
    )
    monkeypatch.setattr(
        "tts_pipeline.finalizer.service.resolve_background_profile",
        lambda **_kwargs: chime_profile,
    )

    reads: list[str] = []

    def fake_read_object_bytes(*, object_key, s3_client=None):
        reads.append(object_key)
        if object_key == final_asset.object_key:
            return b"narration"
        if object_key == "chimes/intro.mp3":
            return b"intro-bytes"
        if object_key == "chimes/outro.mp3":
            return b"outro-bytes"
        return b"bed"

    monkeypatch.setattr(
        "tts_pipeline.finalizer.service.read_object_bytes",
        fake_read_object_bytes,
    )
    monkeypatch.setattr(
        "tts_pipeline.finalizer.service.write_audio_object",
        lambda **kwargs: StoredAudioObject(
            bucket="bucket",
            object_key=kwargs["object_key"],
            byte_size=len(kwargs["audio_bytes"]),
            checksum_sha256=kwargs["checksum_sha256"],
            mime_type=kwargs["mime_type"],
        ),
    )

    captured_kwargs: dict[str, bytes] = {}

    def fake_mix(narration_bytes, bed_bytes, profile, **kwargs):
        captured_kwargs.update(kwargs)
        return b"master-mp3-bytes"

    result = finalize_audio_job_master(None, repo, job, mix_fn=fake_mix)

    assert result.skipped is False
    assert "chimes/intro.mp3" in reads
    assert "chimes/outro.mp3" in reads
    assert captured_kwargs == {
        "intro_chime_bytes": b"intro-bytes",
        "outro_chime_bytes": b"outro-bytes",
    }


def test_finalize_audio_job_master_is_idempotent() -> None:
    job = _job()
    repo = FakeRepo()
    _register_final_asset(repo, job)
    now = datetime.now(UTC)
    existing = TranscriptAudioAssetRecord(
        id=uuid4(),
        audio_job_id=job.id,
        asset_kind=AudioAssetKind.MASTER,
        object_key=f"tenant/transcript/{job.id}/final/master.mp3",
        mime_type="audio/mpeg",
        checksum="master-hash",
        byte_size=1234,
        created_at=now,
    )
    repo.master_assets[str(job.id)] = existing

    def boom_mix(*_args, **_kwargs):  # must not be called
        raise AssertionError("mix_fn should not run on idempotent skip")

    result = finalize_audio_job_master(None, repo, job, mix_fn=boom_mix)

    assert result.skipped is True
    assert result.asset.id == existing.id
    assert any(event[0] == "MASTER_SKIPPED" for event in repo.events)


def test_finalize_audio_job_master_requires_final_asset() -> None:
    job = _job()
    repo = FakeRepo()  # no FINAL registered

    with pytest.raises(FinalAudioMergeError, match="final narration asset missing"):
        finalize_audio_job_master(None, repo, job, mix_fn=lambda *a: b"x")


def test_finalize_manifest_includes_master_asset_fields(monkeypatch) -> None:
    job = _job()
    chunks = [_chunk(job, 0)]
    repo = FakeRepo()
    now = datetime.now(UTC)
    master_asset = TranscriptAudioAssetRecord(
        id=uuid4(),
        audio_job_id=job.id,
        asset_kind=AudioAssetKind.MASTER,
        object_key=f"tenant/transcript/{job.id}/final/master.mp3",
        mime_type="audio/mpeg",
        checksum="master-hash",
        byte_size=4242,
        metadata_json={
            "background_profile_code": "calm_ambient_01",
            "background_track_key": "background/calm_ambient_01.mp3",
        },
        created_at=now,
    )

    monkeypatch.setattr(
        "tts_pipeline.finalizer.service.write_json_object",
        lambda **kwargs: StoredAudioObject(
            bucket="bucket",
            object_key=kwargs["object_key"],
            byte_size=len(kwargs["payload"]),
            checksum_sha256=kwargs["checksum_sha256"],
            mime_type="application/json",
        ),
    )

    result = finalize_audio_job_manifest(
        None,
        repo,
        job,
        chunks,
        master_asset=master_asset,
    )

    payload = result.manifest.to_dict()
    assert payload["master_object_key"] == master_asset.object_key
    assert payload["master_asset_id"] == str(master_asset.id)
    assert payload["master_checksum_sha256"] == "master-hash"
    assert payload["master_byte_size"] == 4242
    assert payload["background_profile_code"] == "calm_ambient_01"
    assert payload["background_track_key"] == "background/calm_ambient_01.mp3"


def test_manifest_without_master_omits_master_fields() -> None:
    job = _job()
    chunks = [_chunk(job, 0)]
    manifest = build_audio_job_manifest(job, chunks)
    payload = manifest.to_dict()
    assert "master_object_key" not in payload
    assert "background_profile_code" not in payload
    assert "pause_plan_summary" not in payload


def test_build_audio_job_manifest_includes_pause_plan_summary() -> None:
    from tts_pipeline.pause_planner.policy import PAUSE_POLICY_VERSION, PROMPT_VERSION

    job = _job(
        metadata_json={
            "pause_plan": {
                "schema_version": "1.0",
                "planner": "openai",
                "model": "gpt-4o-mini",
                "prompt_version": PROMPT_VERSION,
                "policy_version": PAUSE_POLICY_VERSION,
                "total_hold_seconds": 20,
                "holds": [
                    {
                        "hold_id": "h1",
                        "after_beat_index": 0,
                        "hold_seconds": 12,
                        "kind": "practice",
                        "reason": "absorb",
                    },
                    {
                        "hold_id": "h2",
                        "after_beat_index": 1,
                        "hold_seconds": 8,
                        "kind": "section",
                        "reason": "rest",
                    },
                ],
            },
            "mapped_pause_plan": {
                "schema_version": "1.0",
                "total_hold_seconds": 20,
                "holds": [
                    {
                        "hold_id": "h1",
                        "after_beat_index": 0,
                        "after_chunk_index": 0,
                        "hold_seconds": 12,
                        "kind": "practice",
                        "reason": "absorb",
                    },
                    {
                        "hold_id": "h2",
                        "after_beat_index": 1,
                        "after_chunk_index": 1,
                        "hold_seconds": 8,
                        "kind": "section",
                        "reason": "rest",
                    },
                ],
            },
            "pause_plan_versions": {
                "policy_version": PAUSE_POLICY_VERSION,
                "prompt_version": PROMPT_VERSION,
                "model": "gpt-4o-mini",
            },
        }
    )
    chunks = [_chunk(job, 0)]
    payload = build_audio_job_manifest(job, chunks).to_dict()
    assert payload["pause_plan_summary"] == {
        "hold_count": 2,
        "total_hold_seconds": 20,
        "policy_version": PAUSE_POLICY_VERSION,
        "prompt_version": PROMPT_VERSION,
    }
    # Full hold list stays in job metadata only — not dumped into summary.
    assert "holds" not in payload["pause_plan_summary"]


def test_full_final_master_manifest_flow(monkeypatch) -> None:
    """End-to-end finalizer chain: stitch FINAL, mix MASTER, write manifest."""
    job = _job()
    chunks = [_chunk(job, 0), _chunk(job, 1)]
    repo = FakeRepo()
    downloaded: list[str] = []

    def fake_read_object_bytes(*, object_key, s3_client=None):
        downloaded.append(object_key)
        if object_key.endswith("final/final.mp3"):
            return b"narration"
        if object_key.startswith("background/"):
            return b"bed"
        return b"chunk-bytes"

    def fake_merge(chunk_bytes):
        assert len(chunk_bytes) == 2
        return b"merged-final-mp3"

    def fake_mix(narration_bytes, bed_bytes, profile):
        assert narration_bytes == b"narration"
        assert bed_bytes == b"bed"
        return b"master-mp3-bytes"

    monkeypatch.setattr(
        "tts_pipeline.finalizer.service.read_object_bytes",
        fake_read_object_bytes,
    )
    monkeypatch.setattr(
        "tts_pipeline.finalizer.service.write_audio_object",
        lambda **kwargs: StoredAudioObject(
            bucket="bucket",
            object_key=kwargs["object_key"],
            byte_size=len(kwargs["audio_bytes"]),
            checksum_sha256=kwargs["checksum_sha256"],
            mime_type=kwargs["mime_type"],
        ),
    )
    monkeypatch.setattr(
        "tts_pipeline.finalizer.service.write_json_object",
        lambda **kwargs: StoredAudioObject(
            bucket="bucket",
            object_key=kwargs["object_key"],
            byte_size=len(kwargs["payload"]),
            checksum_sha256=kwargs["checksum_sha256"],
            mime_type="application/json",
        ),
    )

    final_result = finalize_audio_job_final(
        None,
        repo,
        job,
        chunks,
        merge_fn=fake_merge,
        correlation_id="corr-flow",
    )
    master_result = finalize_audio_job_master(
        None,
        repo,
        job,
        mix_fn=fake_mix,
        correlation_id="corr-flow",
    )
    manifest_result = finalize_audio_job_manifest(
        None,
        repo,
        job,
        chunks,
        correlation_id="corr-flow",
        final_asset=final_result.asset,
        master_asset=master_result.asset,
    )

    payload = manifest_result.manifest.to_dict()
    assert final_result.asset.asset_kind is AudioAssetKind.FINAL
    assert master_result.asset.asset_kind is AudioAssetKind.MASTER
    assert manifest_result.asset.asset_kind is AudioAssetKind.MANIFEST
    assert payload["final_object_key"] == final_result.asset.object_key
    assert payload["master_object_key"] == master_result.asset.object_key
    assert payload["background_profile_code"] == "calm_ambient_01"
    assert payload["background_track_key"] == "background/calm_ambient_01.mp3"
    assert any(event[0] == "FINAL_MERGED" for event in repo.events)
    assert any(event[0] == "MASTER_MIXED" for event in repo.events)
    assert any(event[0] == "MANIFEST_FINALIZED" for event in repo.events)
    assert repo.job_final_asset_ids[str(job.id)] == final_result.asset.id
    assert len(repo.master_assets) == 1
    assert final_result.asset.object_key in downloaded
    assert "background/calm_ambient_01.mp3" in downloaded
