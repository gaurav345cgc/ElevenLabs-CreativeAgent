"""Phase 6 — TTS audio job intake tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select, text

from db.engine import get_database_url
from db.repositories import CreateTranscriptInput, InsertTranscriptVersionInput, TranscriptRepository
from db.session import build_session_factory, session_scope
from db.orm import TranscriptAudioEventRow
from models.enums import EnhancementMode, TranscriptStatus, VersionKind
from tts_pipeline.intake import AudioJobIntakeService, CreateAudioJobRequest, IntakeValidationError
from tts_pipeline.intake.idempotency import build_audio_job_idempotency_key
from tts_pipeline.intake.validation import validate_enhanced_version, validate_transcript_for_tts
from tts_pipeline.voice_policy import DEFAULT_VOICE_PROFILE_CODE
from models.records import TranscriptRecord, TranscriptVersionRecord


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


def _tts_schema_ready() -> bool:
    if not _postgres_reachable():
        return False
    try:
        engine = create_engine(get_database_url(), pool_pre_ping=True)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'transcript_audio_job'"
                )
            ).first()
        return row is not None
    except Exception:
        return False


requires_tts_schema = pytest.mark.skipif(
    not _tts_schema_ready(),
    reason="TTS tables missing — run alembic upgrade head (migration 002)",
)


def test_build_audio_job_idempotency_key_is_stable() -> None:
    transcript_id = UUID("11111111-2222-3333-4444-555555555555")
    version_id = UUID("66666666-7777-8888-9999-000000000000")
    key = build_audio_job_idempotency_key(
        transcript_id=transcript_id,
        transcript_version_id=version_id,
        voice_profile_code="drew_primary",
    )
    assert key == f"{transcript_id}:{version_id}:drew_primary:tts-v1"


def test_validate_transcript_for_tts_rejects_wrong_status() -> None:
    now = datetime.now(UTC)
    transcript = TranscriptRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        content_type="guided_meditation",
        status=TranscriptStatus.PENDING_ENHANCEMENT,
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(IntakeValidationError, match="not allowed for TTS"):
        validate_transcript_for_tts(transcript, tenant_id=transcript.tenant_id)


def test_validate_enhanced_version_rejects_raw_pattern() -> None:
    transcript_id = uuid4()
    now = datetime.now(UTC)
    version = TranscriptVersionRecord(
        id=uuid4(),
        transcript_id=transcript_id,
        version_kind=VersionKind.RAW_PATTERN,
        content_text="Raw.",
        created_by_agent="pattern_transcript_composer",
        metadata_json={},
        created_at=now,
    )
    with pytest.raises(IntakeValidationError, match="ELEVENLABS_ENHANCED"):
        validate_enhanced_version(version, transcript_id=transcript_id)


@requires_postgres
@requires_tts_schema
def test_create_audio_job_persists_job_and_event() -> None:
    session_factory = build_session_factory()
    transcript_repo = TranscriptRepository(session_factory)
    intake = AudioJobIntakeService(session_factory)
    tenant_id = uuid4()
    transcript_id = uuid4()
    raw_version_id = uuid4()

    with session_scope(session_factory) as session:
        transcript_repo.create_transcript(
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
        transcript_repo.insert_transcript_version(
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
        enhanced = transcript_repo.insert_transcript_version(
            session,
            InsertTranscriptVersionInput(
                transcript_id=transcript_id,
                version_kind=VersionKind.ELEVENLABS_ENHANCED,
                content_text="Enhanced script for TTS.",
                created_by_agent="elevenlabs_script_doctor",
                metadata_json={"schema_version": "1.0", "estimated_duration_minutes": 12},
                source_version_id=raw_version_id,
                enhancement_mode=EnhancementMode.API_CHUNKED,
            ),
        )
        transcript_repo.update_transcript_status(
            session,
            transcript_id,
            TranscriptStatus.PENDING_ENHANCEMENT,
        )
        transcript_repo.claim_for_enhancement(session, transcript_id)
        transcript_repo.set_current_version(session, transcript_id, enhanced.id)
        transcript_repo.update_transcript_status(session, transcript_id, TranscriptStatus.ENHANCED)

    result = intake.create_audio_job(
        CreateAudioJobRequest(
            tenant_id=tenant_id,
            transcript_id=transcript_id,
            transcript_version_id=enhanced.id,
            voice_profile_code=DEFAULT_VOICE_PROFILE_CODE,
        )
    )

    assert result.created is True
    assert result.audio_job.status.value == "CREATED"
    assert result.audio_job.voice_profile_code == DEFAULT_VOICE_PROFILE_CODE
    assert result.audio_job.voice_id == "wgHvco1wiREKN0BdyVx5"
    assert result.audio_job.model_id == "eleven_multilingual_v2"
    assert result.audio_job.output_format == "mp3_44100_128"
    assert result.audio_job.apply_text_normalization == "auto"
    assert result.audio_job.enable_logging is True
    assert result.audio_job.seed == 1337
    assert result.audio_job.metadata_json["traceability"]["transcript"]["wound_id"] == "ml_02"
    assert (
        result.audio_job.metadata_json["traceability"]["transcript_version"]["enhancement_mode"]
        == EnhancementMode.API_CHUNKED.value
    )

    with session_scope(session_factory) as session:
        events = session.scalars(
            select(TranscriptAudioEventRow).where(
                TranscriptAudioEventRow.audio_job_id == result.audio_job.id
            )
        ).all()
        assert len(events) == 1
        assert events[0].event_type == "AUDIO_JOB_CREATED"


@requires_postgres
@requires_tts_schema
def test_create_audio_job_is_idempotent() -> None:
    session_factory = build_session_factory()
    transcript_repo = TranscriptRepository(session_factory)
    intake = AudioJobIntakeService(session_factory)
    tenant_id = uuid4()
    transcript_id = uuid4()

    with session_scope(session_factory) as session:
        transcript_repo.create_transcript(
            session,
            CreateTranscriptInput(
                transcript_id=transcript_id,
                tenant_id=tenant_id,
                content_type="guided_meditation",
            ),
        )
        enhanced = transcript_repo.insert_transcript_version(
            session,
            InsertTranscriptVersionInput(
                transcript_id=transcript_id,
                version_kind=VersionKind.ELEVENLABS_ENHANCED,
                content_text="Enhanced.",
                created_by_agent="elevenlabs_script_doctor",
                metadata_json={},
                enhancement_mode=EnhancementMode.PLAIN_PASTE,
            ),
        )
        transcript_repo.update_transcript_status(
            session,
            transcript_id,
            TranscriptStatus.PENDING_ENHANCEMENT,
        )
        transcript_repo.claim_for_enhancement(session, transcript_id)
        transcript_repo.update_transcript_status(session, transcript_id, TranscriptStatus.ENHANCED)

    request = CreateAudioJobRequest(
        tenant_id=tenant_id,
        transcript_id=transcript_id,
        transcript_version_id=enhanced.id,
    )
    first = intake.create_audio_job(request)
    second = intake.create_audio_job(request)

    assert first.created is True
    assert second.created is False
    assert second.audio_job.id == first.audio_job.id


@requires_postgres
def test_create_audio_job_rejects_non_enhanced_transcript() -> None:
    session_factory = build_session_factory()
    transcript_repo = TranscriptRepository(session_factory)
    intake = AudioJobIntakeService(session_factory)
    tenant_id = uuid4()
    transcript_id = uuid4()

    with session_scope(session_factory) as session:
        transcript_repo.create_transcript(
            session,
            CreateTranscriptInput(
                transcript_id=transcript_id,
                tenant_id=tenant_id,
                content_type="guided_meditation",
                status=TranscriptStatus.PENDING_ENHANCEMENT,
            ),
        )
        enhanced = transcript_repo.insert_transcript_version(
            session,
            InsertTranscriptVersionInput(
                transcript_id=transcript_id,
                version_kind=VersionKind.ELEVENLABS_ENHANCED,
                content_text="Enhanced.",
                created_by_agent="elevenlabs_script_doctor",
                metadata_json={},
            ),
        )

    with pytest.raises(IntakeValidationError, match="not allowed for TTS"):
        intake.create_audio_job(
            CreateAudioJobRequest(
                tenant_id=tenant_id,
                transcript_id=transcript_id,
                transcript_version_id=enhanced.id,
            )
        )
