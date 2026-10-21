"""Phase 11/16 — audio job manifest API tests."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from api.audio_service import AudioJobApiService
from models.enums import AudioAssetKind, AudioJobStatus
from models.records import TranscriptAudioAssetRecord, TranscriptAudioJobRecord


@contextmanager
def _fake_session_scope(_factory):
    yield None


class FakeAudioJobRepo:
    def __init__(self, job: TranscriptAudioJobRecord, manifest_asset: TranscriptAudioAssetRecord | None, manifest_payload: dict) -> None:
        self._session_factory = None
        self.job = job
        self.manifest_asset = manifest_asset
        self.manifest_payload = manifest_payload
        self.final_asset: TranscriptAudioAssetRecord | None = None
        self.master_asset: TranscriptAudioAssetRecord | None = None

    def get_audio_job(self, session, audio_job_id: UUID):
        if audio_job_id == self.job.id:
            return self.job
        return None

    def find_manifest_asset(self, session, audio_job_id: UUID):
        if audio_job_id == self.job.id:
            return self.manifest_asset
        return None

    def find_final_asset(self, session, audio_job_id: UUID):
        if audio_job_id == self.job.id:
            return self.final_asset
        return None

    def find_master_asset(self, session, audio_job_id: UUID):
        if audio_job_id == self.job.id:
            return self.master_asset
        return None


def _job(tenant_id: UUID) -> TranscriptAudioJobRecord:
    now = datetime.now(UTC)
    return TranscriptAudioJobRecord(
        id=uuid4(),
        transcript_id=uuid4(),
        transcript_version_id=uuid4(),
        tenant_id=tenant_id,
        idempotency_key="test",
        voice_id="voice-123",
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
        status=AudioJobStatus.COMPLETED,
        created_at=now,
        updated_at=now,
        final_asset_id=uuid4(),
    )


def test_get_audio_job_manifest_returns_parsed_json(monkeypatch) -> None:
    monkeypatch.setattr("api.audio_service.session_scope", _fake_session_scope)
    tenant_id = uuid4()
    job = _job(tenant_id)
    manifest_asset = TranscriptAudioAssetRecord(
        id=uuid4(),
        audio_job_id=job.id,
        asset_kind=AudioAssetKind.MANIFEST,
        object_key=f"{tenant_id}/{job.transcript_id}/{job.id}/manifest/audio_manifest.json",
        mime_type="application/json",
        created_at=datetime.now(UTC),
    )
    manifest_payload = {
        "schema_version": "tts-audio-manifest-v1",
        "audio_job_id": str(job.id),
        "chunk_count": 1,
        "final_object_key": f"{tenant_id}/{job.transcript_id}/{job.id}/final/final.mp3",
    }
    repo = FakeAudioJobRepo(job, manifest_asset, manifest_payload)
    service = AudioJobApiService(repository=repo)

    monkeypatch.setattr(
        "api.audio_service.read_object_bytes",
        lambda **kwargs: json.dumps(manifest_payload).encode("utf-8"),
    )

    response = service.get_audio_job_manifest(job.id, tenant_id=tenant_id)

    assert response.audio_job_id == job.id
    assert response.manifest["chunk_count"] == 1
    assert response.final_object_key.endswith("final/final.mp3")
    assert response.final_asset_id == job.final_asset_id


def test_get_audio_job_manifest_rejects_wrong_tenant(monkeypatch) -> None:
    monkeypatch.setattr("api.audio_service.session_scope", _fake_session_scope)
    tenant_id = uuid4()
    job = _job(tenant_id)
    repo = FakeAudioJobRepo(job, None, {})
    service = AudioJobApiService(repository=repo)

    with pytest.raises(PermissionError, match="tenant mismatch"):
        service.get_audio_job_manifest(job.id, tenant_id=uuid4())


def test_get_audio_job_status_includes_master_asset_id(monkeypatch) -> None:
    monkeypatch.setattr("api.audio_service.session_scope", _fake_session_scope)
    tenant_id = uuid4()
    job = _job(tenant_id)
    master_id = uuid4()
    repo = FakeAudioJobRepo(job, None, {})
    repo.master_asset = TranscriptAudioAssetRecord(
        id=master_id,
        audio_job_id=job.id,
        asset_kind=AudioAssetKind.MASTER,
        object_key=f"{tenant_id}/{job.transcript_id}/{job.id}/final/master.mp3",
        mime_type="audio/mpeg",
        created_at=datetime.now(UTC),
    )
    service = AudioJobApiService(repository=repo)

    response = service.get_audio_job_status(job.id, tenant_id=tenant_id)

    assert response.master_asset_id == master_id
    assert response.final_asset_id == job.final_asset_id


def test_get_audio_job_status_omits_master_for_pre_feature_jobs(monkeypatch) -> None:
    monkeypatch.setattr("api.audio_service.session_scope", _fake_session_scope)
    tenant_id = uuid4()
    job = _job(tenant_id)
    repo = FakeAudioJobRepo(job, None, {})
    service = AudioJobApiService(repository=repo)

    response = service.get_audio_job_status(job.id, tenant_id=tenant_id)

    assert response.master_asset_id is None
    assert response.pause_hold_count is None
    assert response.pause_total_hold_seconds is None


def test_get_audio_job_status_includes_pause_fields_from_metadata(monkeypatch) -> None:
    monkeypatch.setattr("api.audio_service.session_scope", _fake_session_scope)
    tenant_id = uuid4()
    job = _job(tenant_id).model_copy(
        update={
            "metadata_json": {
                "pause_plan": {
                    "prompt_version": "pause-prompt-v1",
                    "policy_version": "pause-v1",
                    "total_hold_seconds": 27,
                    "holds": [
                        {"hold_id": "h1", "after_beat_index": 0, "hold_seconds": 12, "kind": "practice", "reason": "a"},
                        {"hold_id": "h2", "after_beat_index": 1, "hold_seconds": 15, "kind": "section", "reason": "b"},
                    ],
                }
            }
        }
    )
    repo = FakeAudioJobRepo(job, None, {})
    service = AudioJobApiService(repository=repo)

    response = service.get_audio_job_status(job.id, tenant_id=tenant_id)

    assert response.pause_hold_count == 2
    assert response.pause_total_hold_seconds == 27


def test_create_audio_job_api_request_has_no_pause_fields() -> None:
    from models.requests import CreateAudioJobApiRequest

    fields = set(CreateAudioJobApiRequest.model_fields)
    assert "pause_hold_count" not in fields
    assert "pause_total_hold_seconds" not in fields
    assert "pause_plan" not in fields
    assert "holds" not in fields


def test_get_audio_job_manifest_includes_master_fields_and_urls(monkeypatch) -> None:
    monkeypatch.setattr("api.audio_service.session_scope", _fake_session_scope)
    tenant_id = uuid4()
    job = _job(tenant_id)
    manifest_asset = TranscriptAudioAssetRecord(
        id=uuid4(),
        audio_job_id=job.id,
        asset_kind=AudioAssetKind.MANIFEST,
        object_key=f"{tenant_id}/{job.transcript_id}/{job.id}/manifest/audio_manifest.json",
        mime_type="application/json",
        created_at=datetime.now(UTC),
    )
    master_id = uuid4()
    master_object_key = f"{tenant_id}/{job.transcript_id}/{job.id}/final/master.mp3"
    manifest_payload = {
        "schema_version": "tts-audio-manifest-v1",
        "audio_job_id": str(job.id),
        "chunk_count": 1,
        "final_object_key": f"{tenant_id}/{job.transcript_id}/{job.id}/final/final.mp3",
        "master_object_key": master_object_key,
        "master_asset_id": str(master_id),
    }
    repo = FakeAudioJobRepo(job, manifest_asset, manifest_payload)
    repo.master_asset = TranscriptAudioAssetRecord(
        id=master_id,
        audio_job_id=job.id,
        asset_kind=AudioAssetKind.MASTER,
        object_key=master_object_key,
        mime_type="audio/mpeg",
        created_at=datetime.now(UTC),
    )
    service = AudioJobApiService(repository=repo)

    monkeypatch.setattr(
        "api.audio_service.read_object_bytes",
        lambda **kwargs: json.dumps(manifest_payload).encode("utf-8"),
    )

    presigned: list[str] = []

    def fake_presign(*, object_key, expires_in, s3_client=None):
        presigned.append(object_key)
        return f"https://example.com/{object_key}?expires={expires_in}"

    monkeypatch.setattr("api.audio_service.generate_presigned_object_url", fake_presign)

    response = service.get_audio_job_manifest(
        job.id,
        tenant_id=tenant_id,
        include_urls=True,
        url_expires_in=900,
    )

    assert response.master_asset_id == master_id
    assert response.master_object_key == master_object_key
    assert response.master_url == f"https://example.com/{master_object_key}?expires=900"
    assert response.final_url is not None
    assert master_object_key in presigned


def test_get_audio_job_manifest_prefers_manifest_master_object_key(monkeypatch) -> None:
    monkeypatch.setattr("api.audio_service.session_scope", _fake_session_scope)
    tenant_id = uuid4()
    job = _job(tenant_id)
    manifest_asset = TranscriptAudioAssetRecord(
        id=uuid4(),
        audio_job_id=job.id,
        asset_kind=AudioAssetKind.MANIFEST,
        object_key=f"{tenant_id}/{job.transcript_id}/{job.id}/manifest/audio_manifest.json",
        mime_type="application/json",
        created_at=datetime.now(UTC),
    )
    manifest_master_key = f"{tenant_id}/{job.transcript_id}/{job.id}/final/master-from-manifest.mp3"
    asset_master_key = f"{tenant_id}/{job.transcript_id}/{job.id}/final/master-from-asset.mp3"
    manifest_payload = {
        "schema_version": "tts-audio-manifest-v1",
        "audio_job_id": str(job.id),
        "master_object_key": manifest_master_key,
    }
    repo = FakeAudioJobRepo(job, manifest_asset, manifest_payload)
    repo.master_asset = TranscriptAudioAssetRecord(
        id=uuid4(),
        audio_job_id=job.id,
        asset_kind=AudioAssetKind.MASTER,
        object_key=asset_master_key,
        mime_type="audio/mpeg",
        created_at=datetime.now(UTC),
    )
    service = AudioJobApiService(repository=repo)

    monkeypatch.setattr(
        "api.audio_service.read_object_bytes",
        lambda **kwargs: json.dumps(manifest_payload).encode("utf-8"),
    )

    response = service.get_audio_job_manifest(job.id, tenant_id=tenant_id)

    assert response.master_object_key == manifest_master_key


def test_get_audio_job_manifest_omits_master_for_pre_feature_jobs(monkeypatch) -> None:
    monkeypatch.setattr("api.audio_service.session_scope", _fake_session_scope)
    tenant_id = uuid4()
    job = _job(tenant_id)
    manifest_asset = TranscriptAudioAssetRecord(
        id=uuid4(),
        audio_job_id=job.id,
        asset_kind=AudioAssetKind.MANIFEST,
        object_key=f"{tenant_id}/{job.transcript_id}/{job.id}/manifest/audio_manifest.json",
        mime_type="application/json",
        created_at=datetime.now(UTC),
    )
    final_object_key = f"{tenant_id}/{job.transcript_id}/{job.id}/final/final.mp3"
    manifest_payload = {
        "schema_version": "tts-audio-manifest-v1",
        "audio_job_id": str(job.id),
        "final_object_key": final_object_key,
    }
    repo = FakeAudioJobRepo(job, manifest_asset, manifest_payload)
    service = AudioJobApiService(repository=repo)

    monkeypatch.setattr(
        "api.audio_service.read_object_bytes",
        lambda **kwargs: json.dumps(manifest_payload).encode("utf-8"),
    )

    response = service.get_audio_job_manifest(job.id, tenant_id=tenant_id, include_urls=True)

    assert response.master_asset_id is None
    assert response.master_object_key is None
    assert response.master_url is None
    assert response.final_object_key == final_object_key
    assert response.final_url is not None


def test_get_audio_job_manifest_reflects_post_rollout_manifest_payload(monkeypatch) -> None:
    """Manifest JSON from finalizer flow maps to API master fields and presigned URL."""
    monkeypatch.setattr("api.audio_service.session_scope", _fake_session_scope)
    tenant_id = uuid4()
    job = _job(tenant_id)
    final_object_key = f"{tenant_id}/{job.transcript_id}/{job.id}/final/final.mp3"
    master_object_key = f"{tenant_id}/{job.transcript_id}/{job.id}/final/master.mp3"
    master_id = uuid4()
    manifest_asset = TranscriptAudioAssetRecord(
        id=uuid4(),
        audio_job_id=job.id,
        asset_kind=AudioAssetKind.MANIFEST,
        object_key=f"{tenant_id}/{job.transcript_id}/{job.id}/manifest/audio_manifest.json",
        mime_type="application/json",
        created_at=datetime.now(UTC),
    )
    manifest_payload = {
        "schema_version": "tts-audio-manifest-v1",
        "audio_job_id": str(job.id),
        "transcript_id": str(job.transcript_id),
        "final_object_key": final_object_key,
        "final_asset_id": str(job.final_asset_id),
        "master_object_key": master_object_key,
        "master_asset_id": str(master_id),
        "background_profile_code": "calm_ambient_01",
        "background_track_key": "background/calm_ambient_01.mp3",
    }
    repo = FakeAudioJobRepo(job, manifest_asset, manifest_payload)
    repo.master_asset = TranscriptAudioAssetRecord(
        id=master_id,
        audio_job_id=job.id,
        asset_kind=AudioAssetKind.MASTER,
        object_key=master_object_key,
        mime_type="audio/mpeg",
        created_at=datetime.now(UTC),
    )
    service = AudioJobApiService(repository=repo)

    monkeypatch.setattr(
        "api.audio_service.read_object_bytes",
        lambda **kwargs: json.dumps(manifest_payload).encode("utf-8"),
    )
    monkeypatch.setattr(
        "api.audio_service.generate_presigned_object_url",
        lambda *, object_key, expires_in, s3_client=None: (
            f"https://cdn.example/{object_key}?ttl={expires_in}"
        ),
    )

    status = service.get_audio_job_status(job.id, tenant_id=tenant_id)
    manifest = service.get_audio_job_manifest(
        job.id,
        tenant_id=tenant_id,
        include_urls=True,
    )

    assert status.master_asset_id == master_id
    assert manifest.manifest["master_object_key"] == master_object_key
    assert manifest.master_url == f"https://cdn.example/{master_object_key}?ttl=3600"
    assert manifest.manifest["background_profile_code"] == "calm_ambient_01"
