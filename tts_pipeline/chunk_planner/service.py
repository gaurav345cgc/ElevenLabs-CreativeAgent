"""Plan and persist chunk rows for an audio job."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from db.repositories import AudioJobRepository, CreateAudioChunkInput, TranscriptRepository
from models.enums import AudioChunkStatus, AudioJobStatus
from tts_pipeline.persistence.session import tts_session_scope
from tts_pipeline.chunk_planner.errors import ChunkPlanningError
from tts_pipeline.chunk_planner.models import ChunkBoundarySource, ChunkPlanResult, PlannedChunk
from tts_pipeline.chunk_planner.planner import plan_chunks_from_version
from tts_pipeline.generator.config import DEFAULT_MIME_TYPE

CHUNK_PLAN_PERSISTED_EVENT = "CHUNK_PLAN_PERSISTED"

_ALLOWED_PLAN_STATUSES = frozenset(
    {
        AudioJobStatus.CREATED,
        AudioJobStatus.PLANNING,
        AudioJobStatus.READY,
    }
)


class ChunkPlanningService:
    """Build and persist a chunk plan before ElevenLabs generation."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        transcript_repository: TranscriptRepository | None = None,
        audio_job_repository: AudioJobRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._transcript_repo = transcript_repository or TranscriptRepository(session_factory)
        self._audio_job_repo = audio_job_repository or AudioJobRepository(session_factory)

    def plan_and_persist(
        self,
        audio_job_id: UUID,
        *,
        correlation_id: str | None = None,
    ) -> ChunkPlanResult:
        with tts_session_scope(
            self._session_factory,
            correlation_id=correlation_id,
            audio_job_id=audio_job_id,
        ) as session:
            return self._plan_and_persist(session, audio_job_id, correlation_id=correlation_id)

    def _plan_and_persist(
        self,
        session: Session,
        audio_job_id: UUID,
        *,
        correlation_id: str | None = None,
    ) -> ChunkPlanResult:
        job = self._audio_job_repo.get_audio_job(session, audio_job_id)
        if job is None:
            raise ChunkPlanningError(f"audio job {audio_job_id} not found")

        existing_rows = self._audio_job_repo.list_audio_chunks(session, audio_job_id)
        if existing_rows:
            boundary_source = _boundary_source_from_metadata(existing_rows[0].metadata_json)
            planned = [_planned_from_persisted(row, boundary_source) for row in existing_rows]
            return ChunkPlanResult(
                audio_job_id=audio_job_id,
                boundary_source=boundary_source,
                chunks=planned,
                created=False,
                persisted_chunks=existing_rows,
            )

        if job.status not in _ALLOWED_PLAN_STATUSES:
            raise ChunkPlanningError(
                f"audio job {audio_job_id} status {job.status.value} cannot be planned"
            )

        version = self._transcript_repo.get_transcript_version(
            session,
            job.transcript_id,
            job.transcript_version_id,
        )
        planned_chunks, boundary_source = plan_chunks_from_version(version)

        self._audio_job_repo.mark_job_planning(
            session,
            audio_job_id,
            correlation_id=correlation_id,
        )

        chunk_inputs = [
            CreateAudioChunkInput(
                audio_job_id=job.id,
                transcript_id=job.transcript_id,
                transcript_version_id=job.transcript_version_id,
                chunk_index=chunk.chunk_index,
                source_text=chunk.source_text,
                previous_text=chunk.previous_text,
                next_text=chunk.next_text,
                output_format=job.output_format,
                mime_type=DEFAULT_MIME_TYPE,
                character_count=chunk.character_count,
                estimated_duration_ms=chunk.estimated_duration_ms,
                metadata_json={
                    "boundary_source": chunk.boundary_source.value,
                    "planner_version": "1.0",
                },
                status=AudioChunkStatus.PLANNED,
            )
            for chunk in planned_chunks
        ]
        persisted = self._audio_job_repo.persist_chunk_plan(
            session,
            chunk_inputs,
            correlation_id=correlation_id,
        )

        total_duration_ms = sum(
            chunk.estimated_duration_ms or 0 for chunk in planned_chunks
        )
        self._audio_job_repo.mark_job_ready_after_planning(
            session,
            audio_job_id,
            total_chunks=len(planned_chunks),
            estimated_duration_ms=total_duration_ms or None,
            correlation_id=correlation_id,
        )
        self._audio_job_repo.record_audio_event(
            session,
            audio_job_id,
            CHUNK_PLAN_PERSISTED_EVENT,
            {
                "chunk_count": len(planned_chunks),
                "boundary_source": boundary_source.value,
                "total_estimated_duration_ms": total_duration_ms,
            },
            correlation_id=correlation_id,
        )

        return ChunkPlanResult(
            audio_job_id=audio_job_id,
            boundary_source=boundary_source,
            chunks=planned_chunks,
            created=True,
            persisted_chunks=persisted,
        )


def _boundary_source_from_metadata(metadata: dict | None) -> ChunkBoundarySource:
    if not metadata:
        return ChunkBoundarySource.PARAGRAPHS
    raw = metadata.get("boundary_source")
    try:
        return ChunkBoundarySource(raw)
    except ValueError:
        return ChunkBoundarySource.PARAGRAPHS


def _planned_from_persisted(row, boundary_source: ChunkBoundarySource) -> PlannedChunk:
    return PlannedChunk(
        chunk_index=row.chunk_index,
        source_text=row.source_text,
        previous_text=row.previous_text,
        next_text=row.next_text,
        character_count=row.character_count,
        estimated_duration_ms=row.estimated_duration_ms or 0,
        boundary_source=boundary_source,
    )
