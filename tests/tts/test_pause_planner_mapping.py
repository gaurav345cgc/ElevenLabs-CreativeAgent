"""Phase 7: map pause holds onto TTS chunk indices."""

from __future__ import annotations

import pytest

from tts_pipeline.chunk_planner.models import ChunkBoundarySource, PlannedChunk
from tts_pipeline.pause_planner.anchors import PauseAnchors
from tts_pipeline.pause_planner.errors import PausePlannerValidationError
from tts_pipeline.pause_planner.mapping import map_pause_plan_to_chunks
from tts_pipeline.pause_planner.policy import PAUSE_POLICY_VERSION, PROMPT_VERSION
from tts_pipeline.pause_planner.schema import (
    PauseHold,
    PauseHoldKind,
    PausePlan,
    PausePlannerProvider,
)


def _chunk(index: int, text: str) -> PlannedChunk:
    return PlannedChunk(
        chunk_index=index,
        source_text=text,
        previous_text=None,
        next_text=None,
        character_count=len(text),
        estimated_duration_ms=1000,
        boundary_source=ChunkBoundarySource.BEATS,
    )


def _plan(holds: list[PauseHold]) -> PausePlan:
    return PausePlan(
        planner=PausePlannerProvider.OPENAI,
        model="gpt-4o-mini",
        prompt_version=PROMPT_VERSION,
        policy_version=PAUSE_POLICY_VERSION,
        total_hold_seconds=0,
        holds=holds,
    )


def test_one_to_one_beat_per_chunk() -> None:
    anchors = PauseAnchors(
        beats=["Soften the shoulders.", "Notice the breath.", "Rest before closing."],
        paragraphs=[],
        preferred="beats",
    )
    chunks = [
        _chunk(0, "Soften the shoulders."),
        _chunk(1, "Notice the breath."),
        _chunk(2, "Rest before closing."),
    ]
    plan = _plan(
        [
            PauseHold(
                hold_id="h1",
                after_beat_index=0,
                hold_seconds=12,
                kind=PauseHoldKind.PRACTICE,
                reason="absorb shoulders",
            ),
            PauseHold(
                hold_id="h2",
                after_beat_index=2,
                hold_seconds=40,
                kind=PauseHoldKind.INTEGRATION,
                reason="closing rest",
            ),
        ]
    )
    mapped = map_pause_plan_to_chunks(plan, chunks, anchors)
    assert [h.after_chunk_index for h in mapped.holds] == [0, 2]
    assert mapped.holds[1].after_chunk_index == 2  # allowed after last speech chunk
    assert mapped.total_hold_seconds == 52


def test_merged_beats_into_one_chunk() -> None:
    anchors = PauseAnchors(
        beats=["Soften the shoulders.", "Notice the breath."],
        paragraphs=[],
        preferred="beats",
    )
    chunks = [_chunk(0, "Soften the shoulders. Notice the breath.")]
    plan = _plan(
        [
            PauseHold(
                hold_id="h1",
                after_beat_index=0,
                hold_seconds=10,
                kind=PauseHoldKind.PRACTICE,
                reason="shoulders",
            ),
            PauseHold(
                hold_id="h2",
                after_beat_index=1,
                hold_seconds=10,
                kind=PauseHoldKind.SECTION,
                reason="breath section",
            ),
        ]
    )
    mapped = map_pause_plan_to_chunks(plan, chunks, anchors)
    assert len(mapped.holds) == 1
    hold = mapped.holds[0]
    assert hold.after_chunk_index == 0
    assert hold.kind == PauseHoldKind.SECTION  # highest severity
    assert hold.hold_seconds == 20
    assert "shoulders" in hold.reason and "breath section" in hold.reason


def test_split_paragraph_across_many_chunks_proportional_fallback() -> None:
    # Containment cannot place full paragraph into either half → proportional fallback.
    anchors = PauseAnchors(
        beats=[],
        paragraphs=["AAAA BBBB CCCC DDDD"],
        preferred="paragraphs",
    )
    chunks = [
        _chunk(0, "AAAA BBBB"),
        _chunk(1, "CCCC DDDD"),
    ]
    plan = _plan(
        [
            PauseHold(
                hold_id="h1",
                after_paragraph_index=0,
                hold_seconds=15,
                kind=PauseHoldKind.SECTION,
                reason="after paragraph",
            )
        ]
    )
    mapped = map_pause_plan_to_chunks(plan, chunks, anchors)
    assert len(mapped.holds) == 1
    assert mapped.holds[0].after_chunk_index in {0, 1}


def test_mapping_is_deterministic() -> None:
    anchors = PauseAnchors(
        beats=["One.", "Two."],
        paragraphs=[],
        preferred="beats",
    )
    chunks = [_chunk(0, "One."), _chunk(1, "Two.")]
    plan = _plan(
        [
            PauseHold(
                hold_id="h1",
                after_beat_index=1,
                hold_seconds=8,
                kind=PauseHoldKind.PRACTICE,
                reason="second",
            )
        ]
    )
    first = map_pause_plan_to_chunks(plan, chunks, anchors)
    second = map_pause_plan_to_chunks(plan, chunks, anchors)
    assert first == second


def test_rejects_empty_chunks() -> None:
    anchors = PauseAnchors(beats=["One."], paragraphs=[], preferred="beats")
    plan = _plan(
        [
            PauseHold(
                hold_id="h1",
                after_beat_index=0,
                hold_seconds=8,
                kind=PauseHoldKind.PRACTICE,
                reason="x",
            )
        ]
    )
    with pytest.raises(PausePlannerValidationError, match="chunk list is empty"):
        map_pause_plan_to_chunks(plan, [], anchors)


def test_rejects_out_of_range_unit_index() -> None:
    anchors = PauseAnchors(beats=["One."], paragraphs=[], preferred="beats")
    chunks = [_chunk(0, "One.")]
    plan = _plan(
        [
            PauseHold(
                hold_id="h1",
                after_beat_index=5,
                hold_seconds=8,
                kind=PauseHoldKind.PRACTICE,
                reason="bad index",
            )
        ]
    )
    with pytest.raises(PausePlannerValidationError, match="out of range"):
        map_pause_plan_to_chunks(plan, chunks, anchors)
