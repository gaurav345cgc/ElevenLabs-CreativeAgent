"""Audio job persistence repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from db.exceptions import DuplicateAudioJobError
from db.orm import TranscriptAudioAssetRow, TranscriptAudioChunkRow, TranscriptAudioEventRow, TranscriptAudioJobRow
from db.repositories.types import CreateAudioAssetInput, CreateAudioChunkInput, CreateAudioJobInput
from models.enums import AudioAssetKind, AudioChunkStatus, AudioJobStatus
from models.records import (
    TranscriptAudioAssetRecord,
    TranscriptAudioChunkRecord,
    TranscriptAudioEventRecord,
    TranscriptAudioJobRecord,
)
from observability.logging import log_db_event


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_audio_job_record(row: TranscriptAudioJobRow) -> TranscriptAudioJobRecord:
    return TranscriptAudioJobRecord.model_validate(row)


def _to_audio_event_record(row: TranscriptAudioEventRow) -> TranscriptAudioEventRecord:
    return TranscriptAudioEventRecord.model_validate(row)


def _to_audio_chunk_record(row: TranscriptAudioChunkRow) -> TranscriptAudioChunkRecord:
    return TranscriptAudioChunkRecord.model_validate(row)


def _to_audio_asset_record(row: TranscriptAudioAssetRow) -> TranscriptAudioAssetRecord:
    return TranscriptAudioAssetRecord.model_validate(row)


class AudioJobRepository:
    """Database access for TTS audio jobs and workflow events."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_audio_job(
        self,
        session: Session,
        audio_job_id: UUID,
    ) -> TranscriptAudioJobRecord | None:
        row = session.get(TranscriptAudioJobRow, audio_job_id)
        return _to_audio_job_record(row) if row else None

    def find_latest_audio_job_for_version(
        self,
        session: Session,
        transcript_version_id: UUID,
    ) -> TranscriptAudioJobRecord | None:
        stmt = (
            select(TranscriptAudioJobRow)
            .where(TranscriptAudioJobRow.transcript_version_id == transcript_version_id)
            .order_by(TranscriptAudioJobRow.created_at.desc())
        )
        row = session.scalars(stmt).first()
        return _to_audio_job_record(row) if row else None

    def list_latest_completed_jobs_for_tenant(
        self,
        session: Session,
        tenant_id: UUID,
    ) -> list[TranscriptAudioJobRecord]:
        """Latest COMPLETED audio job per transcript for a tenant (Postgres DISTINCT ON).

        Jobs with metadata_json.library_hidden=true are excluded from the catalog.
        """
        stmt = (
            select(TranscriptAudioJobRow)
            .where(
                TranscriptAudioJobRow.tenant_id == tenant_id,
                TranscriptAudioJobRow.status == AudioJobStatus.COMPLETED.value,
                TranscriptAudioJobRow.metadata_json["library_hidden"].astext.is_distinct_from(
                    "true"
                ),
            )
            .order_by(
                TranscriptAudioJobRow.transcript_id.asc(),
                TranscriptAudioJobRow.created_at.desc(),
            )
            .distinct(TranscriptAudioJobRow.transcript_id)
        )
        return [_to_audio_job_record(row) for row in session.scalars(stmt).all()]

    def find_audio_job_by_idempotency_key(
        self,
        session: Session,
        idempotency_key: str,
    ) -> TranscriptAudioJobRecord | None:
        stmt = select(TranscriptAudioJobRow).where(
            TranscriptAudioJobRow.idempotency_key == idempotency_key
        )
        row = session.scalars(stmt).first()
        return _to_audio_job_record(row) if row else None

    def create_audio_job(
        self,
        session: Session,
        data: CreateAudioJobInput,
        *,
        correlation_id: str | None = None,
    ) -> TranscriptAudioJobRecord:
        existing = self.find_audio_job_by_idempotency_key(session, data.idempotency_key)
        if existing is not None:
            raise DuplicateAudioJobError(
                f"audio job already exists for idempotency_key {data.idempotency_key!r}"
            )

        now = _utc_now()
        row = TranscriptAudioJobRow(
            id=data.audio_job_id or uuid4(),
            transcript_id=data.transcript_id,
            transcript_version_id=data.transcript_version_id,
            tenant_id=data.tenant_id,
            idempotency_key=data.idempotency_key,
            voice_profile_code=data.voice_profile_code,
            voice_id=data.voice_id,
            model_id=data.model_id,
            output_format=data.output_format,
            status=data.status.value,
            enable_logging=data.enable_logging,
            apply_text_normalization=data.apply_text_normalization,
            seed=data.seed,
            metadata_json=data.metadata_json,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        log_db_event(
            "transcript_audio_job_created",
            audio_job_id=row.id,
            transcript_id=row.transcript_id,
            transcript_version_id=row.transcript_version_id,
            tenant_id=row.tenant_id,
            status=row.status,
            correlation_id=correlation_id,
        )
        return _to_audio_job_record(row)

    def record_audio_event(
        self,
        session: Session,
        audio_job_id: UUID,
        event_type: str,
        event_payload: dict[str, Any] | None = None,
        *,
        event_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> TranscriptAudioEventRecord:
        row = TranscriptAudioEventRow(
            id=event_id or uuid4(),
            audio_job_id=audio_job_id,
            event_type=event_type,
            event_payload=event_payload,
            created_at=_utc_now(),
        )
        session.add(row)
        session.flush()
        log_db_event(
            "transcript_audio_event_recorded",
            audio_job_id=audio_job_id,
            event_type=event_type,
            correlation_id=correlation_id,
        )
        return _to_audio_event_record(row)

    def list_audio_chunks(
        self,
        session: Session,
        audio_job_id: UUID,
    ) -> list[TranscriptAudioChunkRecord]:
        stmt = (
            select(TranscriptAudioChunkRow)
            .where(TranscriptAudioChunkRow.audio_job_id == audio_job_id)
            .order_by(TranscriptAudioChunkRow.chunk_index.asc())
        )
        return [_to_audio_chunk_record(row) for row in session.scalars(stmt).all()]

    def persist_chunk_plan(
        self,
        session: Session,
        chunks: list[CreateAudioChunkInput],
        *,
        correlation_id: str | None = None,
    ) -> list[TranscriptAudioChunkRecord]:
        if not chunks:
            raise ValueError("persist_chunk_plan requires at least one chunk")

        audio_job_id = chunks[0].audio_job_id
        existing = self.list_audio_chunks(session, audio_job_id)
        if existing:
            return existing

        now = _utc_now()
        rows: list[TranscriptAudioChunkRow] = []
        for item in chunks:
            row = TranscriptAudioChunkRow(
                id=item.chunk_id or uuid4(),
                audio_job_id=item.audio_job_id,
                transcript_id=item.transcript_id,
                transcript_version_id=item.transcript_version_id,
                chunk_index=item.chunk_index,
                status=item.status.value,
                source_text=item.source_text,
                previous_text=item.previous_text,
                next_text=item.next_text,
                output_format=item.output_format,
                mime_type=item.mime_type,
                character_count=item.character_count,
                estimated_duration_ms=item.estimated_duration_ms,
                metadata_json=item.metadata_json,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            rows.append(row)
        session.flush()
        log_db_event(
            "transcript_audio_chunk_plan_persisted",
            audio_job_id=audio_job_id,
            chunk_count=len(rows),
            correlation_id=correlation_id,
        )
        return [_to_audio_chunk_record(row) for row in rows]

    def mark_job_ready_after_planning(
        self,
        session: Session,
        audio_job_id: UUID,
        *,
        total_chunks: int,
        estimated_duration_ms: int | None,
        correlation_id: str | None = None,
    ) -> TranscriptAudioJobRecord:
        row = session.get(TranscriptAudioJobRow, audio_job_id)
        if row is None:
            raise ValueError(f"audio job {audio_job_id} not found")

        row.status = AudioJobStatus.READY.value
        row.total_chunks = total_chunks
        row.estimated_duration_ms = estimated_duration_ms
        row.updated_at = _utc_now()
        session.flush()
        log_db_event(
            "transcript_audio_job_ready",
            audio_job_id=audio_job_id,
            total_chunks=total_chunks,
            status=row.status,
            correlation_id=correlation_id,
        )
        return _to_audio_job_record(row)

    def mark_job_planning(
        self,
        session: Session,
        audio_job_id: UUID,
        *,
        correlation_id: str | None = None,
    ) -> TranscriptAudioJobRecord:
        row = session.get(TranscriptAudioJobRow, audio_job_id)
        if row is None:
            raise ValueError(f"audio job {audio_job_id} not found")

        if row.status == AudioJobStatus.CREATED.value:
            row.status = AudioJobStatus.PLANNING.value
            row.updated_at = _utc_now()
            session.flush()
            log_db_event(
                "transcript_audio_job_planning",
                audio_job_id=audio_job_id,
                status=row.status,
                correlation_id=correlation_id,
            )
        return _to_audio_job_record(row)

    def mark_job_generating(
        self,
        session: Session,
        audio_job_id: UUID,
        *,
        correlation_id: str | None = None,
    ) -> TranscriptAudioJobRecord:
        row = session.get(TranscriptAudioJobRow, audio_job_id)
        if row is None:
            raise ValueError(f"audio job {audio_job_id} not found")
        row.status = AudioJobStatus.GENERATING.value
        row.finished_at = None
        row.updated_at = _utc_now()
        session.flush()
        log_db_event(
            "transcript_audio_job_generating",
            audio_job_id=audio_job_id,
            status=row.status,
            correlation_id=correlation_id,
        )
        return _to_audio_job_record(row)

    def mark_job_completed(
        self,
        session: Session,
        audio_job_id: UUID,
        *,
        correlation_id: str | None = None,
    ) -> TranscriptAudioJobRecord:
        row = session.get(TranscriptAudioJobRow, audio_job_id)
        if row is None:
            raise ValueError(f"audio job {audio_job_id} not found")
        now = _utc_now()
        row.status = AudioJobStatus.COMPLETED.value
        row.updated_at = now
        row.finished_at = now
        session.flush()
        log_db_event(
            "transcript_audio_job_completed",
            audio_job_id=audio_job_id,
            status=row.status,
            correlation_id=correlation_id,
        )
        return _to_audio_job_record(row)

    def mark_job_failed(
        self,
        session: Session,
        audio_job_id: UUID,
        *,
        last_error: str,
        partially_failed: bool = False,
        correlation_id: str | None = None,
    ) -> TranscriptAudioJobRecord:
        row = session.get(TranscriptAudioJobRow, audio_job_id)
        if row is None:
            raise ValueError(f"audio job {audio_job_id} not found")
        now = _utc_now()
        row.status = (
            AudioJobStatus.PARTIALLY_FAILED.value
            if partially_failed
            else AudioJobStatus.FAILED.value
        )
        row.last_error = last_error
        row.updated_at = now
        row.finished_at = now
        session.flush()
        log_db_event(
            "transcript_audio_job_failed",
            audio_job_id=audio_job_id,
            status=row.status,
            correlation_id=correlation_id,
        )
        return _to_audio_job_record(row)

    def mark_job_created_for_retry(
        self,
        session: Session,
        audio_job_id: UUID,
        *,
        correlation_id: str | None = None,
    ) -> TranscriptAudioJobRecord:
        """Reset a FAILED/PARTIALLY_FAILED job so operator replay can re-plan chunks."""
        row = session.get(TranscriptAudioJobRow, audio_job_id)
        if row is None:
            raise ValueError(f"audio job {audio_job_id} not found")
        now = _utc_now()
        row.status = AudioJobStatus.CREATED.value
        row.last_error = None
        row.finished_at = None
        row.updated_at = now
        session.flush()
        log_db_event(
            "transcript_audio_job_retry_reset",
            audio_job_id=audio_job_id,
            status=row.status,
            correlation_id=correlation_id,
        )
        return _to_audio_job_record(row)

    def archive_completed_jobs_except_transcripts(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        keep_transcript_ids: set[UUID],
        reason: str = "Removed from listen library",
        correlation_id: str | None = None,
    ) -> int:
        """Hide COMPLETED jobs outside keep set from the library (metadata flag; no status change)."""
        stmt = select(TranscriptAudioJobRow).where(
            TranscriptAudioJobRow.tenant_id == tenant_id,
            TranscriptAudioJobRow.status == AudioJobStatus.COMPLETED.value,
            TranscriptAudioJobRow.metadata_json["library_hidden"].astext.is_distinct_from(
                "true"
            ),
        )
        if keep_transcript_ids:
            stmt = stmt.where(
                TranscriptAudioJobRow.transcript_id.notin_(keep_transcript_ids)
            )
        rows = list(session.scalars(stmt).all())
        now = _utc_now()
        for row in rows:
            meta = dict(row.metadata_json or {})
            meta["library_hidden"] = True
            meta["library_hidden_reason"] = reason
            row.metadata_json = meta
            row.updated_at = now
            log_db_event(
                "transcript_audio_job_library_hidden",
                audio_job_id=row.id,
                transcript_id=row.transcript_id,
                status=row.status,
                correlation_id=correlation_id,
            )
        if rows:
            session.flush()
        return len(rows)

    def mark_job_review_required(
        self,
        session: Session,
        audio_job_id: UUID,
        *,
        last_error: str,
        failure_notes: str | None = None,
        correlation_id: str | None = None,
    ) -> TranscriptAudioJobRecord:
        row = session.get(TranscriptAudioJobRow, audio_job_id)
        if row is None:
            raise ValueError(f"audio job {audio_job_id} not found")
        now = _utc_now()
        row.status = AudioJobStatus.REVIEW_REQUIRED.value
        row.last_error = last_error
        row.failure_notes = failure_notes
        row.updated_at = now
        row.finished_at = now
        session.flush()
        log_db_event(
            "transcript_audio_job_review_required",
            audio_job_id=audio_job_id,
            status=row.status,
            correlation_id=correlation_id,
        )
        return _to_audio_job_record(row)

    def reset_job_retry_count(
        self,
        session: Session,
        audio_job_id: UUID,
        *,
        correlation_id: str | None = None,
    ) -> TranscriptAudioJobRecord:
        row = session.get(TranscriptAudioJobRow, audio_job_id)
        if row is None:
            raise ValueError(f"audio job {audio_job_id} not found")
        row.retry_count = 0
        row.updated_at = _utc_now()
        session.flush()
        log_db_event(
            "transcript_audio_job_retry_count_reset",
            audio_job_id=audio_job_id,
            retry_count=row.retry_count,
            correlation_id=correlation_id,
        )
        return _to_audio_job_record(row)

    def increment_job_retry_count(
        self,
        session: Session,
        audio_job_id: UUID,
        *,
        correlation_id: str | None = None,
    ) -> TranscriptAudioJobRecord:
        row = session.get(TranscriptAudioJobRow, audio_job_id)
        if row is None:
            raise ValueError(f"audio job {audio_job_id} not found")
        row.retry_count += 1
        row.updated_at = _utc_now()
        session.flush()
        log_db_event(
            "transcript_audio_job_retry_count_incremented",
            audio_job_id=audio_job_id,
            retry_count=row.retry_count,
            correlation_id=correlation_id,
        )
        return _to_audio_job_record(row)

    def mark_chunk_generating(
        self,
        session: Session,
        chunk_id: UUID,
    ) -> TranscriptAudioChunkRecord:
        row = session.get(TranscriptAudioChunkRow, chunk_id)
        if row is None:
            raise ValueError(f"audio chunk {chunk_id} not found")
        row.status = AudioChunkStatus.GENERATING.value
        row.updated_at = _utc_now()
        session.flush()
        return _to_audio_chunk_record(row)

    def mark_chunk_completed(
        self,
        session: Session,
        chunk_id: UUID,
        *,
        eleven_request_id: str | None,
        output_object_key: str,
        checksum_sha256: str,
        byte_size: int,
        response_headers_json: dict[str, Any],
        metadata_json: dict[str, Any] | None = None,
    ) -> TranscriptAudioChunkRecord:
        row = session.get(TranscriptAudioChunkRow, chunk_id)
        if row is None:
            raise ValueError(f"audio chunk {chunk_id} not found")
        if (
            row.status == AudioChunkStatus.COMPLETED.value
            and row.output_object_key
        ):
            return _to_audio_chunk_record(row)

        row.status = AudioChunkStatus.COMPLETED.value
        row.eleven_request_id = eleven_request_id
        row.output_object_key = output_object_key
        row.updated_at = _utc_now()
        row.metadata_json = {
            **(row.metadata_json or {}),
            **(metadata_json or {}),
            "checksum_sha256": checksum_sha256,
            "byte_size": byte_size,
        }
        row.response_headers_json = response_headers_json
        session.flush()
        return _to_audio_chunk_record(row)

    def mark_chunk_failed(
        self,
        session: Session,
        chunk_id: UUID,
        *,
        error_code: str,
        error_message: str,
        metadata_json: dict[str, Any] | None = None,
    ) -> TranscriptAudioChunkRecord:
        row = session.get(TranscriptAudioChunkRow, chunk_id)
        if row is None:
            raise ValueError(f"audio chunk {chunk_id} not found")
        if row.status == AudioChunkStatus.COMPLETED.value and row.output_object_key:
            return _to_audio_chunk_record(row)

        row.status = AudioChunkStatus.FAILED.value
        row.error_code = error_code
        row.error_message = error_message
        if metadata_json:
            row.metadata_json = {
                **(row.metadata_json or {}),
                **metadata_json,
            }
        row.updated_at = _utc_now()
        session.flush()
        return _to_audio_chunk_record(row)

    def increment_job_chunk_counters(
        self,
        session: Session,
        audio_job_id: UUID,
        *,
        completed_delta: int = 0,
        failed_delta: int = 0,
    ) -> TranscriptAudioJobRecord:
        row = session.get(TranscriptAudioJobRow, audio_job_id)
        if row is None:
            raise ValueError(f"audio job {audio_job_id} not found")
        row.completed_chunks = max(0, row.completed_chunks + completed_delta)
        row.failed_chunks = max(0, row.failed_chunks + failed_delta)
        row.updated_at = _utc_now()
        session.flush()
        return _to_audio_job_record(row)

    def find_final_asset(
        self,
        session: Session,
        audio_job_id: UUID,
    ) -> TranscriptAudioAssetRecord | None:
        stmt = select(TranscriptAudioAssetRow).where(
            TranscriptAudioAssetRow.audio_job_id == audio_job_id,
            TranscriptAudioAssetRow.asset_kind == AudioAssetKind.FINAL.value,
        )
        row = session.scalars(stmt).first()
        return _to_audio_asset_record(row) if row else None

    def find_master_asset(
        self,
        session: Session,
        audio_job_id: UUID,
    ) -> TranscriptAudioAssetRecord | None:
        stmt = select(TranscriptAudioAssetRow).where(
            TranscriptAudioAssetRow.audio_job_id == audio_job_id,
            TranscriptAudioAssetRow.asset_kind == AudioAssetKind.MASTER.value,
        )
        row = session.scalars(stmt).first()
        return _to_audio_asset_record(row) if row else None

    def update_audio_asset(
        self,
        session: Session,
        asset_id: UUID,
        *,
        checksum: str | None = None,
        byte_size: int | None = None,
        metadata_json: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> TranscriptAudioAssetRecord:
        row = session.get(TranscriptAudioAssetRow, asset_id)
        if row is None:
            raise ValueError(f"audio asset {asset_id} not found")
        if checksum is not None:
            row.checksum = checksum
        if byte_size is not None:
            row.byte_size = byte_size
        if metadata_json is not None:
            row.metadata_json = metadata_json
        session.flush()
        log_db_event(
            "transcript_audio_asset_updated",
            audio_job_id=row.audio_job_id,
            asset_id=asset_id,
            asset_kind=row.asset_kind,
            correlation_id=correlation_id,
        )
        return _to_audio_asset_record(row)

    def find_manifest_asset(
        self,
        session: Session,
        audio_job_id: UUID,
    ) -> TranscriptAudioAssetRecord | None:
        stmt = select(TranscriptAudioAssetRow).where(
            TranscriptAudioAssetRow.audio_job_id == audio_job_id,
            TranscriptAudioAssetRow.asset_kind == AudioAssetKind.MANIFEST.value,
        )
        row = session.scalars(stmt).first()
        return _to_audio_asset_record(row) if row else None

    def create_audio_asset(
        self,
        session: Session,
        data: CreateAudioAssetInput,
        *,
        correlation_id: str | None = None,
    ) -> TranscriptAudioAssetRecord:
        asset_id = data.asset_id or uuid4()
        row = TranscriptAudioAssetRow(
            id=asset_id,
            audio_job_id=data.audio_job_id,
            asset_kind=data.asset_kind.value,
            object_key=data.object_key,
            mime_type=data.mime_type,
            checksum=data.checksum,
            byte_size=data.byte_size,
            metadata_json=data.metadata_json,
        )
        session.add(row)
        session.flush()
        log_db_event(
            "transcript_audio_asset_created",
            audio_job_id=data.audio_job_id,
            asset_id=asset_id,
            asset_kind=data.asset_kind.value,
            correlation_id=correlation_id,
        )
        return _to_audio_asset_record(row)

    def set_job_final_asset_id(
        self,
        session: Session,
        audio_job_id: UUID,
        final_asset_id: UUID,
        *,
        correlation_id: str | None = None,
    ) -> TranscriptAudioJobRecord:
        row = session.get(TranscriptAudioJobRow, audio_job_id)
        if row is None:
            raise ValueError(f"audio job {audio_job_id} not found")
        row.final_asset_id = final_asset_id
        row.updated_at = _utc_now()
        session.flush()
        log_db_event(
            "transcript_audio_job_final_asset_set",
            audio_job_id=audio_job_id,
            final_asset_id=final_asset_id,
            correlation_id=correlation_id,
        )
        return _to_audio_job_record(row)

    def merge_audio_job_metadata(
        self,
        session: Session,
        audio_job_id: UUID,
        patch: dict[str, Any],
        *,
        correlation_id: str | None = None,
    ) -> TranscriptAudioJobRecord:
        """Shallow-merge ``patch`` into ``transcript_audio_job.metadata_json``."""
        row = session.get(TranscriptAudioJobRow, audio_job_id)
        if row is None:
            raise ValueError(f"audio job {audio_job_id} not found")
        row.metadata_json = {
            **(row.metadata_json or {}),
            **patch,
        }
        row.updated_at = _utc_now()
        session.flush()
        log_db_event(
            "transcript_audio_job_metadata_merged",
            audio_job_id=audio_job_id,
            correlation_id=correlation_id,
        )
        return _to_audio_job_record(row)
