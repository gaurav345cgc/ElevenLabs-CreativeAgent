"""Integration tests for transcript repository — requires Postgres."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from db.engine import get_database_url
from db.exceptions import DuplicateVersionError, StateTransitionError
from db.repositories import CreateTranscriptInput, InsertTranscriptVersionInput, TranscriptRepository
from db.session import build_session_factory, session_scope
from models.enums import EnhancementMode, TranscriptStatus, VersionKind


def _postgres_reachable() -> bool:
    try:
        engine = create_engine(get_database_url(), pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="Postgres not reachable — set CREATIVE_AGENT_DATABASE_URL in .env or environment",
)


@requires_postgres
def test_repository_lifecycle_and_claim() -> None:
    repo = TranscriptRepository(build_session_factory())
    tenant_id = uuid4()
    transcript_id = uuid4()
    raw_version_id = uuid4()

    with session_scope(repo._session_factory) as session:
        transcript = repo.create_transcript(
            session,
            CreateTranscriptInput(
                transcript_id=transcript_id,
                tenant_id=tenant_id,
                content_type="guided_meditation",
                generation_code="millennial",
                wound_id="ml_02",
                stage_no=1,
            ),
        )
        assert transcript.status == TranscriptStatus.CREATED

        raw = repo.insert_transcript_version(
            session,
            InsertTranscriptVersionInput(
                version_id=raw_version_id,
                transcript_id=transcript_id,
                version_kind=VersionKind.RAW_PATTERN,
                content_text="Raw script.",
                created_by_agent="pattern_transcript_composer",
                metadata_json={"schema_version": "1.0"},
            ),
        )
        assert raw.version_kind == VersionKind.RAW_PATTERN

        repo.update_transcript_status(
            session,
            transcript_id,
            TranscriptStatus.PENDING_ENHANCEMENT,
        )
        repo.record_job_event(session, transcript_id, "TRANSCRIPT_QUEUED", {"raw_version_id": str(raw_version_id)})

    with session_scope(repo._session_factory) as session:
        claimed = repo.claim_for_enhancement(session, transcript_id)
        assert claimed.status == TranscriptStatus.ENHANCING
        assert claimed.enhancement_attempt_count == 1

        enhanced = repo.insert_transcript_version(
            session,
            InsertTranscriptVersionInput(
                transcript_id=transcript_id,
                version_kind=VersionKind.ELEVENLABS_ENHANCED,
                content_text="Enhanced script.",
                created_by_agent="elevenlabs_script_doctor",
                metadata_json={"schema_version": "1.0"},
                source_version_id=raw_version_id,
                enhancement_mode=EnhancementMode.PLAIN_PASTE,
            ),
        )
        repo.set_current_version(session, transcript_id, enhanced.id)
        repo.update_transcript_status(session, transcript_id, TranscriptStatus.ENHANCED)

    with session_scope(repo._session_factory) as session:
        loaded, versions = repo.load_transcript_with_versions(session, transcript_id)
        assert loaded.status == TranscriptStatus.ENHANCED
        assert len(versions) == 2


@requires_postgres
def test_claim_fails_when_not_pending() -> None:
    repo = TranscriptRepository(build_session_factory())
    transcript_id = uuid4()

    with session_scope(repo._session_factory) as session:
        repo.create_transcript(
            session,
            CreateTranscriptInput(
                transcript_id=transcript_id,
                tenant_id=uuid4(),
                content_type="guided_meditation",
                status=TranscriptStatus.CREATED,
            ),
        )

    with session_scope(repo._session_factory) as session:
        with pytest.raises(StateTransitionError):
            repo.claim_for_enhancement(session, transcript_id)


@requires_postgres
def test_duplicate_enhanced_version_rejected() -> None:
    repo = TranscriptRepository(build_session_factory())
    transcript_id = uuid4()
    raw_version_id = uuid4()

    with session_scope(repo._session_factory) as session:
        repo.create_transcript(
            session,
            CreateTranscriptInput(
                transcript_id=transcript_id,
                tenant_id=uuid4(),
                content_type="guided_meditation",
                status=TranscriptStatus.ENHANCING,
            ),
        )
        repo.insert_transcript_version(
            session,
            InsertTranscriptVersionInput(
                version_id=raw_version_id,
                transcript_id=transcript_id,
                version_kind=VersionKind.RAW_PATTERN,
                content_text="Raw.",
                created_by_agent="pattern_transcript_composer",
                metadata_json={},
            ),
        )
        repo.insert_transcript_version(
            session,
            InsertTranscriptVersionInput(
                transcript_id=transcript_id,
                version_kind=VersionKind.ELEVENLABS_ENHANCED,
                content_text="Enhanced v1.",
                created_by_agent="elevenlabs_script_doctor",
                metadata_json={},
                source_version_id=raw_version_id,
                enhancement_mode=EnhancementMode.PLAIN_PASTE,
            ),
        )

    with session_scope(repo._session_factory) as session:
        with pytest.raises(DuplicateVersionError):
            repo.insert_transcript_version(
                session,
                InsertTranscriptVersionInput(
                    transcript_id=transcript_id,
                    version_kind=VersionKind.ELEVENLABS_ENHANCED,
                    content_text="Enhanced duplicate.",
                    created_by_agent="elevenlabs_script_doctor",
                    metadata_json={},
                    source_version_id=raw_version_id,
                    enhancement_mode=EnhancementMode.PLAIN_PASTE,
                ),
            )
        session.rollback()
