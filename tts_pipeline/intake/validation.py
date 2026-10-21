"""Validate transcript and version preconditions for TTS intake."""

from __future__ import annotations

from uuid import UUID

from models.enums import TranscriptStatus, VersionKind
from models.records import TranscriptRecord, TranscriptVersionRecord
from tts_pipeline.intake.errors import IntakeValidationError

ALLOWED_TTS_TRANSCRIPT_STATUSES = frozenset({TranscriptStatus.ENHANCED, TranscriptStatus.APPROVED})


def validate_transcript_for_tts(transcript: TranscriptRecord, *, tenant_id: UUID) -> None:
    if transcript.tenant_id != tenant_id:
        raise IntakeValidationError(
            f"tenant_id mismatch for transcript {transcript.id}"
        )
    if transcript.status not in ALLOWED_TTS_TRANSCRIPT_STATUSES:
        raise IntakeValidationError(
            f"transcript {transcript.id} status {transcript.status.value} is not allowed for TTS; "
            f"expected one of {[s.value for s in ALLOWED_TTS_TRANSCRIPT_STATUSES]}"
        )


def validate_enhanced_version(
    version: TranscriptVersionRecord,
    *,
    transcript_id: UUID,
) -> None:
    if version.transcript_id != transcript_id:
        raise IntakeValidationError(
            f"version {version.id} does not belong to transcript {transcript_id}"
        )
    if version.version_kind not in {VersionKind.ELEVENLABS_ENHANCED, VersionKind.APPROVED_FINAL}:
        raise IntakeValidationError(
            f"version {version.id} kind {version.version_kind.value} is not ELEVENLABS_ENHANCED or APPROVED_FINAL"
        )
