"""Phase 6: pause anchor extraction from enhanced transcript versions."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from models.enums import VersionKind
from models.records import TranscriptVersionRecord
from tts_pipeline.pause_planner.anchors import PauseAnchors, extract_pause_anchors
from tts_pipeline.pause_planner.errors import PausePlannerValidationError


def _version(
    *,
    content_text: str = "",
    content_json: dict | None = None,
) -> TranscriptVersionRecord:
    return TranscriptVersionRecord(
        id=uuid4(),
        transcript_id=uuid4(),
        version_kind=VersionKind.ELEVENLABS_ENHANCED,
        content_text=content_text,
        created_by_agent="test",
        metadata_json={},
        created_at=datetime.now(timezone.utc),
        content_json=content_json,
    )


def test_prefers_non_blank_beats_from_content_json() -> None:
    version = _version(
        content_text="Fallback paragraph one.\n\nFallback paragraph two.",
        content_json={
            "schema_version": "1.0",
            "beats": ["  Soften the shoulders.  ", "", "  Notice the breath.  ", "   "],
        },
    )
    anchors = extract_pause_anchors(version)
    assert isinstance(anchors, PauseAnchors)
    assert anchors.preferred == "beats"
    assert anchors.beats == ["Soften the shoulders.", "Notice the breath."]
    assert len(anchors.paragraphs) == 2


def test_falls_back_to_paragraphs_when_beats_empty() -> None:
    version = _version(
        content_text="First beat of settling.\n\n\nSecond beat of breath.\n\n",
        content_json={"beats": ["", "  "]},
    )
    anchors = extract_pause_anchors(version)
    assert anchors.preferred == "paragraphs"
    assert anchors.beats == []
    assert anchors.paragraphs == ["First beat of settling.", "Second beat of breath."]


def test_falls_back_when_content_json_missing_or_beats_absent() -> None:
    version = _version(content_text="Only paragraph.", content_json=None)
    anchors = extract_pause_anchors(version)
    assert anchors.preferred == "paragraphs"
    assert anchors.paragraphs == ["Only paragraph."]


def test_rejects_when_both_empty() -> None:
    version = _version(content_text="   ", content_json={"beats": []})
    with pytest.raises(PausePlannerValidationError, match="no usable beats or paragraphs"):
        extract_pause_anchors(version)


def test_ignores_non_string_beat_entries() -> None:
    version = _version(
        content_text="",
        content_json={"beats": [None, 12, "Valid cue.", {"x": 1}]},
    )
    anchors = extract_pause_anchors(version)
    assert anchors.preferred == "beats"
    assert anchors.beats == ["Valid cue."]
