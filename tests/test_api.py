"""Phase 10 — intake API tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.audio_service import AudioJobApiService
from api import dependencies
from api.main import create_app
from api.transcript_service import TranscriptApiService
from db.engine import get_database_url
from db.repositories import AudioJobRepository, TranscriptRepository
from db.session import build_session_factory, session_scope
from models.enums import TranscriptStatus
from models.requests import CreateTranscriptRequest
from queues.tts_publisher import InMemoryTtsPublisher
from tests.test_transcript_repository import requires_postgres
from transcript_composer.composition_service import CompositionService
from transcript_composer.script_generator import TemplateScriptGenerator
from transcript_composer.service import build_agent1_service_for_tests


def _sample_payload(**overrides) -> dict:
    payload = {
        "tenant_id": str(uuid4()),
        "content_type": "guided_meditation",
        "generation_code": "millennial",
        "wound_id": "ml_02",
        "stage_no": 2,
        "target_duration_minutes": 10,
        "pillar_code": "p04",
    }
    payload.update(overrides)
    return payload


def _headers(tenant_id: str) -> dict:
    import os
    h = {"X-Tenant-Id": tenant_id}
    key = os.environ.get("CREATIVE_AGENT_API_KEY")
    if key:
        h["X-API-Key"] = key
    return h


@pytest.fixture
def api_client():
    database_url = get_database_url()
    agent1, publisher = build_agent1_service_for_tests(database_url=database_url)
    agent1._composition = CompositionService(generator=TemplateScriptGenerator())
    repository = TranscriptRepository(build_session_factory(database_url))
    tts_publisher = InMemoryTtsPublisher()
    audio_service = AudioJobApiService(
        repository=AudioJobRepository(build_session_factory(database_url)),
        publisher=tts_publisher,
    )
    api_service = TranscriptApiService(
        repository=repository,
        publisher=publisher,
        audio_job_service=audio_service,
        tts_publisher=tts_publisher,
    )

    app = create_app()
    app.dependency_overrides[dependencies.get_agent1_service] = lambda: agent1
    app.dependency_overrides[dependencies.get_transcript_api_service] = lambda: api_service
    app.dependency_overrides[dependencies.get_transcript_repository] = lambda: repository

    with TestClient(app) as client:
        yield client, publisher, repository, tts_publisher


def test_health_endpoint() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_transcript_validation_error() -> None:
    import os
    client = TestClient(create_app())
    headers = {}
    key = os.environ.get("CREATIVE_AGENT_API_KEY")
    if key:
        headers["X-API-Key"] = key
    response = client.post("/transcripts", json={"tenant_id": str(uuid4())}, headers=headers)
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"


@requires_postgres
def test_create_and_get_transcript(api_client) -> None:
    client, publisher, _repository, _tts = api_client
    tenant_id = str(uuid4())
    headers = _headers(tenant_id)

    create = client.post("/transcripts", json=_sample_payload(tenant_id=tenant_id), headers=headers)
    assert create.status_code == 201
    created = create.json()
    assert created["status"] == "PENDING_ENHANCEMENT"
    assert created["title"]
    assert len(publisher.messages) == 1

    transcript_id = created["transcript_id"]
    get_resp = client.get(f"/transcripts/{transcript_id}", headers=headers)
    assert get_resp.status_code == 200
    status_body = get_resp.json()
    assert status_body["transcript_id"] == transcript_id
    assert status_body["tenant_id"] == tenant_id
    assert status_body["status"] == "PENDING_ENHANCEMENT"


@requires_postgres
def test_list_versions_hides_content_by_default(api_client) -> None:
    client, _publisher, _repository, _tts = api_client
    tenant_id = str(uuid4())
    headers = _headers(tenant_id)

    create = client.post("/transcripts", json=_sample_payload(tenant_id=tenant_id), headers=headers)
    transcript_id = create.json()["transcript_id"]

    versions = client.get(f"/transcripts/{transcript_id}/versions", headers=headers)
    assert versions.status_code == 200
    items = versions.json()["versions"]
    assert len(items) == 1
    assert items[0]["content_text"] is None

    with_content = client.get(
        f"/transcripts/{transcript_id}/versions",
        headers=headers,
        params={"include_content": "true"},
    )
    assert with_content.json()["versions"][0]["content_text"]


@requires_postgres
def test_get_transcript_rejects_wrong_tenant(api_client) -> None:
    client, _publisher, _repository, _tts = api_client
    tenant_id = str(uuid4())
    create = client.post(
        "/transcripts",
        json=_sample_payload(tenant_id=tenant_id),
        headers=_headers(tenant_id),
    )
    transcript_id = create.json()["transcript_id"]

    other_tenant = str(uuid4())
    response = client.get(
        f"/transcripts/{transcript_id}",
        headers=_headers(other_tenant),
    )
    assert response.status_code == 403


@requires_postgres
def test_retry_enhancement_for_failed_transcript(api_client) -> None:
    client, publisher, repository, _tts = api_client
    tenant_id = str(uuid4())
    headers = _headers(tenant_id)

    create = client.post("/transcripts", json=_sample_payload(tenant_id=tenant_id), headers=headers)
    transcript_id = create.json()["transcript_id"]

    with session_scope(repository._session_factory) as session:
        repository.update_transcript_status(
            session,
            transcript_id,
            TranscriptStatus.FAILED_ENHANCEMENT,
            last_error="simulated failure",
        )

    before_messages = len(publisher.messages)
    retry = client.post(f"/transcripts/{transcript_id}/retry-enhancement", headers=headers)
    assert retry.status_code == 200
    body = retry.json()
    assert body["status"] == "PENDING_ENHANCEMENT"
    assert len(publisher.messages) == before_messages + 1

    status = client.get(f"/transcripts/{transcript_id}", headers=headers)
    assert status.json()["status"] == "PENDING_ENHANCEMENT"


@requires_postgres
def test_wait_returns_accepted_while_pending(api_client) -> None:
    client, _publisher, _repository, _tts = api_client
    tenant_id = str(uuid4())
    headers = _headers(tenant_id)

    create = client.post("/transcripts", json=_sample_payload(tenant_id=tenant_id), headers=headers)
    transcript_id = create.json()["transcript_id"]

    wait = client.get(
        f"/transcripts/{transcript_id}/wait",
        headers=headers,
        params={"max_wait_seconds": 1, "include_content": "false"},
    )
    assert wait.status_code == 202
    body = wait.json()
    assert body["ready"] is False
    assert body["status"] == "PENDING_ENHANCEMENT"


@requires_postgres
def test_list_transcripts(api_client) -> None:
    client, _publisher, _repository, _tts = api_client
    tenant_id = str(uuid4())
    headers = _headers(tenant_id)

    # Verify initially empty
    resp = client.get("/transcripts", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []

    # Create one
    create = client.post("/transcripts", json=_sample_payload(tenant_id=tenant_id), headers=headers)
    assert create.status_code == 201

    # Verify it shows up in list
    resp = client.get("/transcripts", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["status"] == "PENDING_ENHANCEMENT"


@requires_postgres
def test_approve_transcript(api_client) -> None:
    client, _publisher, repository, tts_publisher = api_client
    tenant_id = str(uuid4())
    headers = _headers(tenant_id)

    # Create a transcript
    create = client.post("/transcripts", json=_sample_payload(tenant_id=tenant_id), headers=headers)
    transcript_id = create.json()["transcript_id"]

    # Transition to ENHANCING then insert ELEVENLABS_ENHANCED version and transition to ENHANCED status
    from uuid import UUID
    from db.repositories.types import InsertTranscriptVersionInput
    from models.enums import VersionKind
    
    tid = UUID(transcript_id)
    with session_scope(repository._session_factory) as session:
        # Move to ENHANCING
        repository.claim_for_enhancement(session, tid)
        # Create ELEVENLABS_ENHANCED version
        repository.insert_transcript_version(
            session,
            InsertTranscriptVersionInput(
                transcript_id=tid,
                version_kind=VersionKind.ELEVENLABS_ENHANCED,
                content_text="This is enhanced speakable text.",
                created_by_agent="agent2",
                metadata_json={},
            )
        )
        # Move to ENHANCED
        repository.update_transcript_status(session, tid, TranscriptStatus.ENHANCED)

    # Approve with dashboard pause markers — should lock plan and enqueue TTS.
    approve_resp = client.post(
        f"/transcripts/{transcript_id}/approve",
        headers=headers,
        json={
            "approved_text": (
                "This is final approved text.\n\n[pause 8s]\n\n"
                "Second beat after the hold."
            )
        },
    )
    assert approve_resp.status_code == 200
    body = approve_resp.json()
    assert body["status"] == "APPROVED"
    assert body["audio_job_id"]
    assert body["tts_queue_message_id"]
    assert body.get("tts_enqueue_error") in (None, "")
    assert len(tts_publisher.messages) == 1
    assert str(tts_publisher.messages[0].audio_job_id) == body["audio_job_id"]

    # Verify approved version is set as current and has version kind APPROVED_FINAL
    versions = client.get(f"/transcripts/{transcript_id}/versions?include_content=true", headers=headers).json()
    items = versions["versions"]
    # Should have RAW_PATTERN, ELEVENLABS_ENHANCED, and APPROVED_FINAL
    assert len(items) == 3
    approved_ver = next(v for v in items if v["version_kind"] == "APPROVED_FINAL")
    assert "This is final approved text." in approved_ver["content_text"]
    assert "Second beat after the hold." in approved_ver["content_text"]
    assert "[pause" not in (approved_ver["content_text"] or "")
    assert approved_ver["metadata_json"].get("human_pause_hold_count") == 1
    assert body["current_version_id"] == approved_ver["version_id"]
