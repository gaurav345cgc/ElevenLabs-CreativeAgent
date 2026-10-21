"""Deterministic guard: never more than N consecutive spoken sentences without a hold."""

from __future__ import annotations

from tts_pipeline.pause_planner.anchors import PauseAnchors
from tts_pipeline.pause_planner.density import enforce_pause_density
from tts_pipeline.pause_planner.policy import PAUSE_POLICY_VERSION, PROMPT_VERSION
from tts_pipeline.pause_planner.schema import (
    PauseHold,
    PauseHoldKind,
    PausePlan,
    PausePlannerProvider,
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


def test_inserts_hold_when_gap_exceeds_cap() -> None:
    # 5 one-sentence beats, no holds -> break before each subsequent sentence.
    anchors = PauseAnchors(
        beats=["One.", "Two.", "Three.", "Four.", "Five."],
        paragraphs=[],
        preferred="beats",
    )
    plan = _plan([])

    result = enforce_pause_density(plan, anchors, max_sentences=1)

    inserted = [h for h in result.holds if h.hold_id.startswith("density_guard_")]
    assert len(inserted) >= 4
    assert inserted[0].after_beat_index == 0
    assert inserted[0].kind == PauseHoldKind.PRACTICE


def test_already_compliant_plan_is_untouched() -> None:
    anchors = PauseAnchors(
        beats=["One.", "Two.", "Three.", "Four."],
        paragraphs=[],
        preferred="beats",
    )
    plan = _plan(
        [
            PauseHold(
                hold_id="h1",
                after_beat_index=0,
                hold_seconds=8,
                kind=PauseHoldKind.PRACTICE,
                reason="already paced",
            ),
            PauseHold(
                hold_id="h2",
                after_beat_index=1,
                hold_seconds=8,
                kind=PauseHoldKind.PRACTICE,
                reason="already paced",
            ),
            PauseHold(
                hold_id="h3",
                after_beat_index=2,
                hold_seconds=8,
                kind=PauseHoldKind.PRACTICE,
                reason="already paced",
            ),
        ]
    )

    result = enforce_pause_density(plan, anchors, max_sentences=1)

    assert result is plan
    assert result.holds == plan.holds


def test_existing_hold_resets_the_counter_no_duplicate() -> None:
    anchors = PauseAnchors(
        beats=["One.", "Two.", "Three."],
        paragraphs=[],
        preferred="beats",
    )
    plan = _plan(
        [
            PauseHold(
                hold_id="h1",
                after_beat_index=0,
                hold_seconds=8,
                kind=PauseHoldKind.PRACTICE,
                reason="section break",
            ),
            PauseHold(
                hold_id="h2",
                after_beat_index=1,
                hold_seconds=8,
                kind=PauseHoldKind.PRACTICE,
                reason="section break",
            ),
        ]
    )

    result = enforce_pause_density(plan, anchors, max_sentences=1)

    inserted = [h for h in result.holds if h.hold_id.startswith("density_guard_")]
    assert inserted == []


def test_single_oversized_unit_gets_hold_after_it_without_crashing() -> None:
    # One beat with 5 sentences and no internal anchor -> guard can only place
    # the hold after the whole unit (known v1 limitation when units aren't expanded).
    anchors = PauseAnchors(
        beats=["One. Two. Three. Four. Five."],
        paragraphs=[],
        preferred="beats",
    )
    plan = _plan([])

    result = enforce_pause_density(plan, anchors, max_sentences=1)

    inserted = [h for h in result.holds if h.hold_id.startswith("density_guard_")]
    assert len(inserted) == 1
    assert inserted[0].after_beat_index == 0


def test_paragraph_anchors_use_after_paragraph_index() -> None:
    anchors = PauseAnchors(
        beats=[],
        paragraphs=["One.", "Two."],
        preferred="paragraphs",
    )
    plan = _plan([])

    result = enforce_pause_density(plan, anchors, max_sentences=1)

    inserted = [h for h in result.holds if h.hold_id.startswith("density_guard_")]
    assert len(inserted) == 1
    assert inserted[0].after_paragraph_index == 0
    assert inserted[0].after_beat_index is None


def test_empty_anchors_returns_plan_unchanged() -> None:
    anchors = PauseAnchors(beats=[], paragraphs=[], preferred="beats")
    plan = _plan([])

    result = enforce_pause_density(plan, anchors, max_sentences=1)

    assert result is plan
