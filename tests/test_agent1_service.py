"""Agent 1 service and handler tests."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from db.engine import get_database_url
from models.enums import TranscriptStatus, VersionKind
from models.requests import CreateTranscriptRequest
from transcript_composer.handler import handler, parse_event
from transcript_composer.service import build_agent1_service_for_tests
from db.repositories import TranscriptRepository
from db.session import build_session_factory, session_scope
from tests.test_transcript_repository import _postgres_reachable, requires_postgres


def _sample_request(**overrides) -> CreateTranscriptRequest:
    payload = {
        "tenant_id": uuid4(),
        "content_type": "guided_meditation",
        "generation_code": "millennial",
        "wound_id": "ml_02",
        "stage_no": 2,
        "target_duration_minutes": 10,
        "pillar_code": "p04",
    }
    payload.update(overrides)
    return CreateTranscriptRequest(**payload)


def test_parse_event_direct_payload() -> None:
    request = _sample_request()
    parsed = parse_event(request.model_dump(mode="json"))
    assert parsed.wound_id == "ml_02"


def test_parse_event_api_gateway_body() -> None:
    request = _sample_request()
    event = {"body": json.dumps(request.model_dump(mode="json"))}
    parsed = parse_event(event)
    assert parsed.generation_code == "millennial"


def test_handler_validation_error() -> None:
    response = handler({"wound_id": "invalid"}, None)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error_code"] == "VALIDATION_ERROR"


@requires_postgres
def test_agent1_service_persists_and_queues() -> None:
    service, publisher = build_agent1_service_for_tests(database_url=get_database_url())
    request = _sample_request()
    result = service.run(request)

    assert result.output.status == TranscriptStatus.PENDING_ENHANCEMENT
    assert len(publisher.messages) == 1
    message = publisher.messages[0]
    assert message.transcript_id == result.output.transcript_id
    assert message.raw_version_id == result.output.version_id
    assert message.tenant_id == request.tenant_id

    repo = TranscriptRepository(build_session_factory())
    with session_scope(repo._session_factory) as session:
        transcript, versions = repo.load_transcript_with_versions(
            session,
            result.output.transcript_id,
        )
        assert transcript.status == TranscriptStatus.PENDING_ENHANCEMENT
        assert len(versions) == 1
        assert versions[0].version_kind == VersionKind.RAW_PATTERN
        assert versions[0].content_text == result.output.transcript_text
        assert versions[0].metadata_json["title"] == result.output.title


@requires_postgres
def test_handler_end_to_end_with_injected_service(monkeypatch: pytest.MonkeyPatch) -> None:
    if not _postgres_reachable():
        pytest.skip("Postgres not reachable")

    import importlib

    handler_module = importlib.import_module("transcript_composer.handler")
    service, publisher = build_agent1_service_for_tests(database_url=get_database_url())
    monkeypatch.setattr(handler_module, "Agent1Service", lambda *args, **kwargs: service)

    request = _sample_request()
    response = handler(request.model_dump(mode="json"), None)
    assert response["statusCode"] == 201
    body = json.loads(response["body"])
    assert body["status"] == "PENDING_ENHANCEMENT"
    assert body["title"]
    assert len(publisher.messages) == 1
