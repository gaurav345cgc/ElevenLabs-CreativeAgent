"""Idempotency helpers for enhancement queue consumers."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from db.exceptions import TranscriptNotFoundError
from db.repositories import TranscriptRepository
from models.enums import TranscriptStatus
from models.messages import EnhancementJobMessage


@dataclass(frozen=True, slots=True)
class HandoffValidation:
    transcript_id: UUID
    tenant_id: UUID
    raw_version_id: UUID
    status: TranscriptStatus


class HandoffValidationError(ValueError):
    """Raised when an SQS message does not match database state."""


def find_existing_enhanced_version(
    repository: TranscriptRepository,
    session: Session,
    message: EnhancementJobMessage,
):
    return repository.find_enhanced_version(
        session,
        message.raw_version_id,
        message.requested_output_mode.value,
    )


def validate_enhancement_handoff(
    repository: TranscriptRepository,
    session: Session,
    message: EnhancementJobMessage,
) -> HandoffValidation:
    """Ensure the queue message references a valid pending raw transcript version."""
    transcript = repository.get_transcript(session, message.transcript_id)
    if transcript.tenant_id != message.tenant_id:
        raise HandoffValidationError(
            f"tenant_id mismatch for transcript {message.transcript_id}"
        )

    _, versions = repository.load_transcript_with_versions(session, message.transcript_id)
    raw_version = next((v for v in versions if v.id == message.raw_version_id), None)
    if raw_version is None:
        raise HandoffValidationError(
            f"raw_version_id {message.raw_version_id} not found for transcript {message.transcript_id}"
        )

    return HandoffValidation(
        transcript_id=message.transcript_id,
        tenant_id=message.tenant_id,
        raw_version_id=message.raw_version_id,
        status=transcript.status,
    )


def should_skip_duplicate_enhancement(
    repository: TranscriptRepository,
    session: Session,
    message: EnhancementJobMessage,
) -> bool:
    """Return True when Agent 2 work is already complete for this idempotency key."""
    if find_existing_enhanced_version(repository, session, message) is not None:
        return True

    try:
        transcript = repository.get_transcript(session, message.transcript_id)
    except TranscriptNotFoundError:
        return False

    return transcript.status == TranscriptStatus.ENHANCED
