"""Transcript persistence repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from db.exceptions import (
    DuplicateVersionError,
    StateTransitionError,
    TranscriptNotFoundError,
    TranscriptVersionNotFoundError,
)
from db.orm import TranscriptJobEventRow, TranscriptRow, TranscriptVersionRow
from db.repositories.types import CreateTranscriptInput, InsertTranscriptVersionInput
from db.state import assert_transition_allowed
from models.enums import TranscriptStatus
from models.records import TranscriptJobEventRecord, TranscriptRecord, TranscriptVersionRecord
from observability.logging import log_db_event


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_transcript_record(row: TranscriptRow) -> TranscriptRecord:
    return TranscriptRecord.model_validate(row)


def _to_version_record(row: TranscriptVersionRow) -> TranscriptVersionRecord:
    return TranscriptVersionRecord.model_validate(row)


def _to_event_record(row: TranscriptJobEventRow) -> TranscriptJobEventRecord:
    return TranscriptJobEventRecord.model_validate(row)


class TranscriptRepository:
    """Database access for transcript entities, versions, and audit events."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_transcript(
        self,
        session: Session,
        data: CreateTranscriptInput,
        *,
        correlation_id: str | None = None,
    ) -> TranscriptRecord:
        transcript_id = data.transcript_id or uuid4()
        now = _utc_now()
        row = TranscriptRow(
            id=transcript_id,
            tenant_id=data.tenant_id,
            asset_id=data.asset_id,
            content_type=data.content_type,
            generation_code=data.generation_code,
            wound_id=data.wound_id,
            stage_no=data.stage_no,
            pillar_code=data.pillar_code,
            status=data.status.value,
            enhancement_attempt_count=0,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        log_db_event(
            "transcript_created",
            transcript_id=row.id,
            tenant_id=row.tenant_id,
            status=row.status,
            correlation_id=correlation_id,
        )
        return _to_transcript_record(row)

    def insert_transcript_version(
        self,
        session: Session,
        data: InsertTranscriptVersionInput,
        *,
        correlation_id: str | None = None,
    ) -> TranscriptVersionRecord:
        version_id = data.version_id or uuid4()
        row = TranscriptVersionRow(
            id=version_id,
            transcript_id=data.transcript_id,
            version_kind=data.version_kind.value,
            content_text=data.content_text,
            content_json=data.content_json,
            created_by_agent=data.created_by_agent,
            metadata_json=data.metadata_json,
            source_version_id=data.source_version_id,
            enhancement_mode=data.enhancement_mode.value if data.enhancement_mode else None,
            created_at=_utc_now(),
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            raise DuplicateVersionError(
                "enhanced version already exists for source_version_id and enhancement_mode"
            ) from exc
        log_db_event(
            "transcript_version_inserted",
            transcript_id=data.transcript_id,
            version_id=row.id,
            version_kind=row.version_kind,
            correlation_id=correlation_id,
        )
        return _to_version_record(row)

    def update_transcript_status(
        self,
        session: Session,
        transcript_id: UUID,
        new_status: TranscriptStatus,
        *,
        last_error: str | None = None,
        correlation_id: str | None = None,
    ) -> TranscriptRecord:
        row = session.get(TranscriptRow, transcript_id)
        if row is None:
            raise TranscriptNotFoundError(f"transcript {transcript_id} not found")

        current = TranscriptStatus(row.status)
        assert_transition_allowed(current, new_status)

        row.status = new_status.value
        row.updated_at = _utc_now()
        if last_error is not None:
            row.last_error = last_error

        session.flush()
        log_db_event(
            "transcript_status_updated",
            transcript_id=transcript_id,
            status=row.status,
            correlation_id=correlation_id,
        )
        return _to_transcript_record(row)

    def set_current_version(
        self,
        session: Session,
        transcript_id: UUID,
        version_id: UUID,
        *,
        correlation_id: str | None = None,
    ) -> TranscriptRecord:
        row = session.get(TranscriptRow, transcript_id)
        if row is None:
            raise TranscriptNotFoundError(f"transcript {transcript_id} not found")

        version = session.get(TranscriptVersionRow, version_id)
        if version is None or version.transcript_id != transcript_id:
            raise TranscriptNotFoundError(
                f"version {version_id} not found for transcript {transcript_id}"
            )

        row.current_version_id = version_id
        row.updated_at = _utc_now()
        session.flush()
        log_db_event(
            "transcript_current_version_set",
            transcript_id=transcript_id,
            version_id=version_id,
            correlation_id=correlation_id,
        )
        return _to_transcript_record(row)

    def replace_transcript_version_content(
        self,
        session: Session,
        version_id: UUID,
        *,
        content_text: str,
        content_json: dict[str, Any] | None,
        metadata_json: dict[str, Any] | None,
        correlation_id: str | None = None,
    ) -> TranscriptVersionRecord:
        """Overwrite spoken content + metadata on an existing version (e.g. re-approve)."""
        row = session.get(TranscriptVersionRow, version_id)
        if row is None:
            raise TranscriptVersionNotFoundError(f"version {version_id} not found")
        row.content_text = content_text
        row.content_json = content_json
        row.metadata_json = metadata_json
        session.flush()
        log_db_event(
            "transcript_version_content_replaced",
            transcript_id=row.transcript_id,
            version_id=version_id,
            correlation_id=correlation_id,
        )
        return _to_version_record(row)

    def merge_transcript_version_metadata(
        self,
        session: Session,
        version_id: UUID,
        patch: dict[str, Any],
        *,
        correlation_id: str | None = None,
    ) -> TranscriptVersionRecord:
        """Shallow-merge ``patch`` into ``transcript_version.metadata_json``."""
        row = session.get(TranscriptVersionRow, version_id)
        if row is None:
            raise TranscriptVersionNotFoundError(f"version {version_id} not found")
        row.metadata_json = {
            **(row.metadata_json or {}),
            **patch,
        }
        session.flush()
        log_db_event(
            "transcript_version_metadata_merged",
            transcript_id=row.transcript_id,
            version_id=version_id,
            correlation_id=correlation_id,
        )
        return _to_version_record(row)

    def record_job_event(
        self,
        session: Session,
        transcript_id: UUID,
        event_type: str,
        event_payload: dict[str, Any] | None = None,
        *,
        event_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> TranscriptJobEventRecord:
        row = TranscriptJobEventRow(
            id=event_id or uuid4(),
            transcript_id=transcript_id,
            event_type=event_type,
            event_payload=event_payload,
            created_at=_utc_now(),
        )
        session.add(row)
        session.flush()
        log_db_event(
            "transcript_job_event_recorded",
            transcript_id=transcript_id,
            event_type=event_type,
            correlation_id=correlation_id,
        )
        return _to_event_record(row)

    def get_transcript(
        self,
        session: Session,
        transcript_id: UUID,
    ) -> TranscriptRecord:
        row = session.get(TranscriptRow, transcript_id)
        if row is None:
            raise TranscriptNotFoundError(f"transcript {transcript_id} not found")
        return _to_transcript_record(row)

    def get_transcript_version(
        self,
        session: Session,
        transcript_id: UUID,
        version_id: UUID,
    ) -> TranscriptVersionRecord:
        row = session.get(TranscriptVersionRow, version_id)
        if row is None or row.transcript_id != transcript_id:
            raise TranscriptVersionNotFoundError(
                f"version {version_id} not found for transcript {transcript_id}"
            )
        return _to_version_record(row)

    def load_transcript_with_versions(
        self,
        session: Session,
        transcript_id: UUID,
    ) -> tuple[TranscriptRecord, list[TranscriptVersionRecord]]:
        transcript = self.get_transcript(session, transcript_id)
        stmt = (
            select(TranscriptVersionRow)
            .where(TranscriptVersionRow.transcript_id == transcript_id)
            .order_by(TranscriptVersionRow.created_at.asc())
        )
        versions = [_to_version_record(row) for row in session.scalars(stmt).all()]
        return transcript, versions

    def claim_for_enhancement(
        self,
        session: Session,
        transcript_id: UUID,
        *,
        correlation_id: str | None = None,
    ) -> TranscriptRecord:
        """Atomically move PENDING_ENHANCEMENT -> ENHANCING."""
        stmt = (
            update(TranscriptRow)
            .where(
                TranscriptRow.id == transcript_id,
                TranscriptRow.status == TranscriptStatus.PENDING_ENHANCEMENT.value,
            )
            .values(
                status=TranscriptStatus.ENHANCING.value,
                enhancement_attempt_count=TranscriptRow.enhancement_attempt_count + 1,
                updated_at=_utc_now(),
            )
            .returning(TranscriptRow)
        )
        row = session.scalars(stmt).one_or_none()
        if row is None:
            raise StateTransitionError(
                f"transcript {transcript_id} is not in PENDING_ENHANCEMENT or does not exist"
            )
        session.flush()
        log_db_event(
            "transcript_claimed_for_enhancement",
            transcript_id=transcript_id,
            status=row.status,
            enhancement_attempt_count=row.enhancement_attempt_count,
            correlation_id=correlation_id,
        )
        return _to_transcript_record(row)

    def mark_enhancement_failed(
        self,
        session: Session,
        transcript_id: UUID,
        error_message: str,
        *,
        review_required: bool = False,
        correlation_id: str | None = None,
    ) -> TranscriptRecord:
        target = (
            TranscriptStatus.REVIEW_REQUIRED
            if review_required
            else TranscriptStatus.FAILED_ENHANCEMENT
        )
        row = session.get(TranscriptRow, transcript_id)
        if row is None:
            raise TranscriptNotFoundError(f"transcript {transcript_id} not found")

        current = TranscriptStatus(row.status)
        if current not in {TranscriptStatus.ENHANCING, TranscriptStatus.PENDING_ENHANCEMENT}:
            assert_transition_allowed(current, target)

        row.status = target.value
        row.last_error = error_message
        row.updated_at = _utc_now()
        session.flush()
        log_db_event(
            "transcript_enhancement_failed",
            transcript_id=transcript_id,
            status=row.status,
            correlation_id=correlation_id,
        )
        return _to_transcript_record(row)

    def find_enhanced_version(
        self,
        session: Session,
        source_version_id: UUID,
        enhancement_mode: str,
    ) -> TranscriptVersionRecord | None:
        stmt = select(TranscriptVersionRow).where(
            TranscriptVersionRow.source_version_id == source_version_id,
            TranscriptVersionRow.enhancement_mode == enhancement_mode,
        )
        row = session.scalars(stmt).first()
        return _to_version_record(row) if row else None

    def list_transcripts(
        self,
        session: Session,
        *,
        status: TranscriptStatus | None = None,
        tenant_id: UUID | None = None,
    ) -> list[TranscriptRecord]:
        stmt = select(TranscriptRow)
        if status is not None:
            stmt = stmt.where(TranscriptRow.status == status.value)
        if tenant_id is not None:
            stmt = stmt.where(TranscriptRow.tenant_id == tenant_id)
        stmt = stmt.order_by(TranscriptRow.updated_at.desc())
        return [_to_transcript_record(row) for row in session.scalars(stmt).all()]

    def dismiss_enhanced_for_tenant(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        reason: str = "Cleared from Script Hub pending review",
        correlation_id: str | None = None,
    ) -> list[UUID]:
        """Move ENHANCED scripts out of the Script Hub approval queue (→ REVIEW_REQUIRED)."""
        stmt = select(TranscriptRow).where(
            TranscriptRow.tenant_id == tenant_id,
            TranscriptRow.status == TranscriptStatus.ENHANCED.value,
        )
        rows = list(session.scalars(stmt).all())
        dismissed: list[UUID] = []
        for row in rows:
            assert_transition_allowed(
                TranscriptStatus.ENHANCED,
                TranscriptStatus.REVIEW_REQUIRED,
            )
            row.status = TranscriptStatus.REVIEW_REQUIRED.value
            row.last_error = reason
            row.updated_at = _utc_now()
            dismissed.append(row.id)
            log_db_event(
                "transcript_dismissed_from_script_hub",
                transcript_id=row.id,
                status=row.status,
                correlation_id=correlation_id,
            )
        if rows:
            session.flush()
        return dismissed
