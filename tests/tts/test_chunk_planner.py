"""Phase 7 — chunk planner tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text

from db.engine import get_database_url
from db.repositories import CreateTranscriptInput, InsertTranscriptVersionInput, TranscriptRepository
from db.session import build_session_factory, session_scope
from models.enums import AudioChunkStatus, AudioJobStatus, EnhancementMode, TranscriptStatus, VersionKind
from models.records import TranscriptVersionRecord
from tts_pipeline.chunk_planner import (
    ChunkBoundarySource,
    ChunkPlanValidationError,
    ChunkPlanningService,
    plan_chunks_from_version,
    validate_chunk_plan,
)
from tts_pipeline.chunk_planner.config import MIN_CHUNK_CHARS
from tts_pipeline.intake import AudioJobIntakeService, CreateAudioJobRequest
from tts_pipeline.voice_policy import DEFAULT_VOICE_PROFILE_CODE


def _postgres_reachable() -> bool:
    try:
        engine = create_engine(get_database_url(), pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _tts_schema_ready() -> bool:
    if not _postgres_reachable():
        return False
    try:
        engine = create_engine(get_database_url(), pool_pre_ping=True)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'transcript_audio_chunk'"
                )
            ).first()
        return row is not None
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="Postgres not reachable",
)
requires_tts_schema = pytest.mark.skipif(
    not _tts_schema_ready(),
    reason="TTS tables missing — run alembic upgrade head",
)


def _version(
    *,
    content_text: str,
    content_json: dict | None = None,
) -> TranscriptVersionRecord:
    now = datetime.now(UTC)
    return TranscriptVersionRecord(
        id=uuid4(),
        transcript_id=uuid4(),
        version_kind=VersionKind.ELEVENLABS_ENHANCED,
        content_text=content_text,
        content_json=content_json,
        created_by_agent="elevenlabs_script_doctor",
        metadata_json={"schema_version": "1.0"},
        created_at=now,
    )


MEDITATION_TEXT = (
    "Welcome to this guided meditation journey.\n\n"
    "Take one easy breath and feel your body settle.\n\n"
    "Notice the weight of your shoulders and let them soften.\n\n"
    "Stay with the quiet rhythm of your breathing."
)

LONG_MEDITATION_TEXT = (
    MEDITATION_TEXT
    + "\n\n"
    + "Allow each inhale to arrive without effort or strain.\n\n"
    + "Allow each exhale to leave a little more space in the body.\n\n"
    + "If thoughts appear, notice them gently and return to breath.\n\n"
    + "There is nothing you need to fix in this moment.\n\n"
    + "Rest in the quiet support beneath you.\n\n"
    + "When you are ready, return slowly with softness."
)


def test_plans_from_content_text_with_sentence_boundaries() -> None:
    """Agent2 chunk metadata is ignored; narration text drives sentence-safe boundaries."""
    version = _version(
        content_text=(
            "Take a deep breath and focus on the atmosphere around you. "
            "Let your shoulders soften with each exhale."
        ),
        content_json={
            "schema_version": "1.0",
            "chunks": [
                {"sequence": 0, "text": "Take a deep breath and focus on", "previous_text": None},
                {"sequence": 1, "text": "the atmosphere around you.", "previous_text": None},
            ],
        },
    )
    chunks, source = plan_chunks_from_version(version)
    assert source is ChunkBoundarySource.SENTENCES
    assert len(chunks) == 2
    assert "focus on the atmosphere" in chunks[0].source_text
    assert "shoulders soften" in chunks[1].source_text


def test_uses_beats_when_no_prebuilt_chunks() -> None:
    version = _version(
        content_text=LONG_MEDITATION_TEXT,
        content_json={
            "schema_version": "1.0",
            "beats": [
                "Welcome to this guided meditation journey.",
                "Take one easy breath and feel your body settle.",
                "Notice the weight of your shoulders and let them soften.",
                "Stay with the quiet rhythm of your breathing.",
                "Allow each inhale to arrive without effort or strain.",
                "Allow each exhale to leave a little more space in the body.",
                "If thoughts appear, notice them gently and return to breath.",
                "There is nothing you need to fix in this moment.",
                "Rest in the quiet support beneath you.",
                "When you are ready, return slowly with softness.",
            ],
        },
    )
    chunks, source = plan_chunks_from_version(version)
    assert source is ChunkBoundarySource.SENTENCES
    assert len(chunks) >= 2
    assert all(chunk.previous_text or chunk.next_text or len(chunks) == 1 for chunk in chunks)


def test_falls_back_to_sentence_chunks_without_beats() -> None:
    version = _version(content_text=LONG_MEDITATION_TEXT, content_json={"schema_version": "1.0"})
    chunks, source = plan_chunks_from_version(version)
    assert source is ChunkBoundarySource.SENTENCES
    assert len(chunks) >= 2


def test_builds_previous_and_next_text() -> None:
    chunks, _ = plan_chunks_from_version(_version(content_text=LONG_MEDITATION_TEXT))
    assert len(chunks) >= 2
    assert chunks[0].next_text is not None
    assert chunks[-1].previous_text is not None
    if len(chunks) > 2:
        middle = chunks[1]
        assert middle.previous_text is not None
        assert middle.next_text is not None


def test_estimates_character_count_and_duration() -> None:
    chunks, _ = plan_chunks_from_version(_version(content_text=MEDITATION_TEXT))
    for chunk in chunks:
        assert chunk.character_count == len(chunk.source_text)
        assert chunk.estimated_duration_ms > 0


def test_validate_chunk_plan_rejects_empty() -> None:
    with pytest.raises(ChunkPlanValidationError, match="at least one chunk"):
        validate_chunk_plan([])


def test_merges_undersized_leading_chunk_with_next() -> None:
    version = _version(
        content_text="Hi.\n\n"
        + ("Take one easy breath and feel your body settle comfortably now. " * 3),
        content_json={"schema_version": "1.0"},
    )
    chunks, _ = plan_chunks_from_version(version)
    assert all(chunk.character_count >= MIN_CHUNK_CHARS for chunk in chunks)


@requires_postgres
@requires_tts_schema
def test_plan_and_persist_is_idempotent() -> None:
    session_factory = build_session_factory()
    transcript_repo = TranscriptRepository(session_factory)
    intake = AudioJobIntakeService(session_factory)
    planner = ChunkPlanningService(session_factory)
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
                content_text=LONG_MEDITATION_TEXT,
                created_by_agent="elevenlabs_script_doctor",
                metadata_json={"schema_version": "1.0"},
                content_json={
                    "schema_version": "1.0",
                    "beats": [
                        "Welcome to this guided meditation journey.",
                        "Take one easy breath and feel your body settle.",
                        "Notice the weight of your shoulders and let them soften.",
                        "Stay with the quiet rhythm of your breathing.",
                        "Allow each inhale to arrive without effort or strain.",
                        "Allow each exhale to leave a little more space in the body.",
                        "If thoughts appear, notice them gently and return to breath.",
                        "There is nothing you need to fix in this moment.",
                        "Rest in the quiet support beneath you.",
                        "When you are ready, return slowly with softness.",
                    ],
                },
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

    job = intake.create_audio_job(
        CreateAudioJobRequest(
            tenant_id=tenant_id,
            transcript_id=transcript_id,
            transcript_version_id=enhanced.id,
            voice_profile_code=DEFAULT_VOICE_PROFILE_CODE,
        )
    ).audio_job

    first = planner.plan_and_persist(job.id)
    second = planner.plan_and_persist(job.id)

    assert first.created is True
    assert second.created is False
    assert len(first.chunks) == len(second.chunks)
    assert first.chunks[0].source_text == second.chunks[0].source_text

    with session_scope(session_factory) as session:
        status, total_chunks = session.execute(
            text("SELECT status, total_chunks FROM transcript_audio_job WHERE id = :job_id"),
            {"job_id": str(job.id)},
        ).one()
        assert status == AudioJobStatus.READY.value
        assert total_chunks == len(first.chunks)

        chunk_rows = session.execute(
            text(
                "SELECT chunk_index, status FROM transcript_audio_chunk "
                "WHERE audio_job_id = :job_id ORDER BY chunk_index"
            ),
            {"job_id": str(job.id)},
        ).all()
        assert len(chunk_rows) == len(first.chunks)
        assert all(row[1] == AudioChunkStatus.PLANNED.value for row in chunk_rows)
