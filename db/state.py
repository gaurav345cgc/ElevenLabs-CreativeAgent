"""Allowed transcript status transitions."""

from __future__ import annotations

from models.enums import TranscriptStatus

ALLOWED_TRANSITIONS: dict[TranscriptStatus, frozenset[TranscriptStatus]] = {
    TranscriptStatus.CREATED: frozenset({TranscriptStatus.PENDING_ENHANCEMENT}),
    TranscriptStatus.PENDING_ENHANCEMENT: frozenset(
        {TranscriptStatus.ENHANCING, TranscriptStatus.FAILED_ENHANCEMENT}
    ),
    TranscriptStatus.ENHANCING: frozenset(
        {
            TranscriptStatus.ENHANCED,
            TranscriptStatus.FAILED_ENHANCEMENT,
            TranscriptStatus.REVIEW_REQUIRED,
        }
    ),
    TranscriptStatus.ENHANCED: frozenset({TranscriptStatus.APPROVED, TranscriptStatus.REVIEW_REQUIRED}),
    TranscriptStatus.FAILED_ENHANCEMENT: frozenset(
        {TranscriptStatus.PENDING_ENHANCEMENT, TranscriptStatus.REVIEW_REQUIRED}
    ),
    TranscriptStatus.REVIEW_REQUIRED: frozenset(
        {TranscriptStatus.PENDING_ENHANCEMENT, TranscriptStatus.ENHANCED, TranscriptStatus.APPROVED}
    ),
    TranscriptStatus.APPROVED: frozenset({TranscriptStatus.REVIEW_REQUIRED}),
}


def assert_transition_allowed(
    current: TranscriptStatus,
    target: TranscriptStatus,
) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        msg = f"transition {current.value} -> {target.value} is not allowed"
        raise ValueError(msg)
