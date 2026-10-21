"""Deterministic guardrail enforcing a hard cap on consecutive spoken sentences.

``pause_planner/prompt.py`` already asks the LLM to place a hold after every
spoken sentence, but that is only a prompt instruction — nothing verifies the
model actually complied. This module is the backstop: it walks the same
beat/paragraph anchors the LLM saw, counts sentences deterministically, and
inserts a synthetic hold anywhere the model's plan would otherwise let the cap slip.

Runs *before* ``normalize_pause_plan`` (see ``orchestrator/states.py``), so the
existing clamp/budget-fit pass in ``policy.py`` accounts for any synthetic holds
added here automatically.
"""

from __future__ import annotations

from tts_pipeline.chunk_planner.sentences import split_sentences
from tts_pipeline.pause_planner.anchors import PauseAnchors
from tts_pipeline.pause_planner.policy import KIND_BOUNDS
from tts_pipeline.pause_planner.schema import PauseHold, PauseHoldKind, PausePlan

# Product pacing: a silence hold after every spoken sentence (Script Hub + TTS).
DEFAULT_MAX_SENTENCES = 1
DENSITY_GUARD_KIND = PauseHoldKind.PRACTICE
DENSITY_GUARD_REASON_TEMPLATE = "Density guard: caps consecutive spoken sentences at {max_sentences}."


def enforce_pause_density(
    plan: PausePlan,
    anchors: PauseAnchors,
    *,
    max_sentences: int = DEFAULT_MAX_SENTENCES,
) -> PausePlan:
    """Insert synthetic holds so no run of unbroken sentences exceeds ``max_sentences``.

    No-op when the plan already respects the cap. Deterministic and pure — same
    inputs always produce the same synthetic holds in the same order.
    """
    units = anchors.beats if anchors.preferred == "beats" else anchors.paragraphs
    if not units:
        return plan

    existing_unit_indexes = _existing_hold_unit_indexes(plan, anchors)
    sentence_counts = [len(split_sentences(unit)) for unit in units]

    synthetic_holds: list[PauseHold] = []
    running_count = 0
    for unit_index, count in enumerate(sentence_counts):
        # Adding this unit would blow the cap — break *before* it (previous unit)
        # rather than let the run grow past max_sentences.
        if running_count > 0 and running_count + count > max_sentences:
            synthetic_holds.append(_build_synthetic_hold(unit_index - 1, anchors, max_sentences))
            running_count = 0

        running_count += count

        if unit_index in existing_unit_indexes:
            running_count = 0
        elif running_count > max_sentences:
            # A single unit alone exceeds the cap (no earlier boundary to break at) —
            # place the hold right after it. Known v1 limitation: can't split mid-unit.
            synthetic_holds.append(_build_synthetic_hold(unit_index, anchors, max_sentences))
            running_count = 0

    if not synthetic_holds:
        return plan

    return plan.model_copy(update={"holds": [*plan.holds, *synthetic_holds]})


def _existing_hold_unit_indexes(plan: PausePlan, anchors: PauseAnchors) -> set[int]:
    if anchors.preferred == "beats":
        return {hold.after_beat_index for hold in plan.holds if hold.after_beat_index is not None}
    return {hold.after_paragraph_index for hold in plan.holds if hold.after_paragraph_index is not None}


def _build_synthetic_hold(unit_index: int, anchors: PauseAnchors, max_sentences: int) -> PauseHold:
    hold_seconds = KIND_BOUNDS[DENSITY_GUARD_KIND].prefer_min
    reason = DENSITY_GUARD_REASON_TEMPLATE.format(max_sentences=max_sentences)
    if anchors.preferred == "beats":
        return PauseHold(
            hold_id=f"density_guard_{unit_index}",
            after_beat_index=unit_index,
            hold_seconds=hold_seconds,
            kind=DENSITY_GUARD_KIND,
            reason=reason,
        )
    return PauseHold(
        hold_id=f"density_guard_{unit_index}",
        after_paragraph_index=unit_index,
        hold_seconds=hold_seconds,
        kind=DENSITY_GUARD_KIND,
        reason=reason,
    )
