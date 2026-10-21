"""Agent 2 service and end-to-end enhancement tests."""

from __future__ import annotations

from uuid import uuid4

from db.engine import get_database_url
from db.repositories import TranscriptRepository
from db.session import build_session_factory, session_scope
from models.enums import EnhancementMode, TranscriptStatus, VersionKind
from models.requests import CreateTranscriptRequest
from queues.consumer import HandoffOutcome
from tests.test_transcript_repository import requires_postgres
from transcript_composer.composition_service import CompositionService
from transcript_composer.script_generator import TemplateScriptGenerator
from transcript_composer.service import build_agent1_service_for_tests
from tts_enhancer.consumer_service import build_enhancement_consumer_for_tests
from tts_enhancer.enhancement_service import build_enhancement_service_for_tests


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


@requires_postgres
def test_enhancement_service_persists_enhanced_version() -> None:
    database_url = get_database_url()
    agent1, publisher = build_agent1_service_for_tests(
        database_url=database_url,
    )
    agent1._composition = CompositionService(generator=TemplateScriptGenerator())
    request = _sample_request()
    agent1_result = agent1.run(request)
    message = publisher.messages[0]

    enhancer = build_enhancement_service_for_tests(database_url=database_url)
    output = enhancer.run(message)

    assert output.transcript_id == agent1_result.output.transcript_id
    assert output.source_version_id == agent1_result.output.version_id
    assert output.enhanced_full_script
    assert output.enhanced_content.beats

    repo = TranscriptRepository(build_session_factory(database_url))
    with session_scope(repo._session_factory) as session:
        transcript, versions = repo.load_transcript_with_versions(
            session,
            output.transcript_id,
        )
        assert transcript.status == TranscriptStatus.ENHANCED
        assert transcript.current_version_id == output.version_id
        assert len(versions) == 2
        enhanced = next(v for v in versions if v.version_kind == VersionKind.ELEVENLABS_ENHANCED)
        assert enhanced.content_text == output.enhanced_full_script
        assert enhanced.source_version_id == agent1_result.output.version_id
        assert enhanced.enhancement_mode == EnhancementMode.PLAIN_PASTE


@requires_postgres
def test_consumer_end_to_end_enhances_transcript() -> None:
    database_url = get_database_url()
    agent1, publisher = build_agent1_service_for_tests(database_url=database_url)
    agent1._composition = CompositionService(generator=TemplateScriptGenerator())
    agent1.run(_sample_request())
    message = publisher.messages[0]

    consumer = build_enhancement_consumer_for_tests(database_url=database_url)
    outcome = consumer.handle(message)
    assert outcome == HandoffOutcome.PROCESSED

    repo = TranscriptRepository(build_session_factory(database_url))
    with session_scope(repo._session_factory) as session:
        transcript, versions = repo.load_transcript_with_versions(
            session,
            message.transcript_id,
        )
        assert transcript.status == TranscriptStatus.ENHANCED
        assert any(v.version_kind == VersionKind.ELEVENLABS_ENHANCED for v in versions)


@requires_postgres
def test_duplicate_enhancement_is_idempotent() -> None:
    database_url = get_database_url()
    agent1, publisher = build_agent1_service_for_tests(database_url=database_url)
    agent1._composition = CompositionService(generator=TemplateScriptGenerator())
    agent1.run(_sample_request())
    message = publisher.messages[0]

    consumer = build_enhancement_consumer_for_tests(database_url=database_url)
    assert consumer.handle(message) == HandoffOutcome.PROCESSED
    assert consumer.handle(message) == HandoffOutcome.SKIPPED_DUPLICATE

    repo = TranscriptRepository(build_session_factory(database_url))
    with session_scope(repo._session_factory) as session:
        _, versions = repo.load_transcript_with_versions(session, message.transcript_id)
        enhanced_versions = [
            v for v in versions if v.version_kind == VersionKind.ELEVENLABS_ENHANCED
        ]
        assert len(enhanced_versions) == 1
