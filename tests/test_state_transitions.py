"""Unit tests for status transition rules."""

import pytest

from db.state import ALLOWED_TRANSITIONS, assert_transition_allowed
from models.enums import TranscriptStatus


def test_pending_to_enhancing_allowed() -> None:
    assert_transition_allowed(
        TranscriptStatus.PENDING_ENHANCEMENT,
        TranscriptStatus.ENHANCING,
    )


def test_enhancing_to_enhanced_allowed() -> None:
    assert_transition_allowed(TranscriptStatus.ENHANCING, TranscriptStatus.ENHANCED)


def test_created_to_enhanced_not_allowed() -> None:
    with pytest.raises(ValueError):
        assert_transition_allowed(TranscriptStatus.CREATED, TranscriptStatus.ENHANCED)


def test_all_statuses_have_transition_map() -> None:
    for status in TranscriptStatus:
        assert status in ALLOWED_TRANSITIONS
