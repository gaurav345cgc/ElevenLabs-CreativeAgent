"""Server-side pause hold bounds and duration budgeting.

Pure functions only — no I/O. Callers persist and log as needed.

Over-budget behavior
--------------------
1. Clamp each hold into its kind range (v1: clamp into range, never drop for being low).
2. Recompute ``total_hold_seconds``.
3. If ``estimated_speech + total_holds + tail > target * (1 + tolerance)``,
   scale all holds down proportionally (integer seconds, then re-clamp to kind min).
4. If still over budget after every hold is at its kind minimum, drop holds in
   priority order: ``other`` (shortest first), then ``practice`` (shortest first),
   then ``section``, then ``integration``, until within budget or no holds remain.
5. Cap count at ``MAX_HOLDS_PER_JOB`` using the same drop priority.

Empty holds (v1)
----------------
The planner may return ``{"holds": []}`` for very short scripts. ``PausePlan`` and
``normalize_pause_plan`` accept an empty hold list; downstream stitch behaves like
today (speech only) until holds are mapped. When speech already exceeds wall-clock,
normalize keeps prefer-min holds instead of wiping the plan (listening density).
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass

from tts_pipeline.pause_planner.errors import PausePlannerError
from tts_pipeline.pause_planner.schema import PauseHold, PauseHoldKind, PausePlan
from models.duration_budget import DURATION_TOLERANCE_RATIO

logger = logging.getLogger("creative_agent.tts.pause_planner")

PAUSE_POLICY_VERSION = "pause-v7"
PROMPT_VERSION = "pause-prompt-v7"

MIN_HOLD_SECONDS = 2
MAX_HOLD_SECONDS = 90
# One practice hold after nearly every sentence → longer scripts need headroom.
MAX_HOLDS_PER_JOB = 150
DEFAULT_FAIL_ON_PLANNER_ERROR = True
DEFAULT_TAIL_ESTIMATE_SECONDS = 4

# Small deterministic wobble so recurring hold lengths (e.g. many 8s practice
# holds) don't land on suspiciously identical numbers. Seeded per hold_id so the
# same plan replays with the same jittered seconds (see create_or_load_pause_plan).
HOLD_JITTER_RATIO = 0.10
# If holds undershoot the ideal hold budget, scale up toward it (still clamped).
HOLD_UNDERFILL_EXPAND_RATIO = 0.85


@dataclass(frozen=True, slots=True)
class HoldKindBounds:
    """Allowed and preferred second ranges for one hold kind."""

    min_seconds: int
    max_seconds: int
    prefer_min: int
    prefer_max: int


KIND_BOUNDS: dict[PauseHoldKind, HoldKindBounds] = {
    # Short rests after each spoken sentence — slightly brisker than v6 (4s).
    PauseHoldKind.PRACTICE: HoldKindBounds(2, 12, 2, 5),
    PauseHoldKind.SECTION: HoldKindBounds(8, 30, 10, 20),
    PauseHoldKind.INTEGRATION: HoldKindBounds(15, 75, 20, 40),
    PauseHoldKind.OTHER: HoldKindBounds(MIN_HOLD_SECONDS, MAX_HOLD_SECONDS, 2, 5),
}

# Drop order: lowest priority first. Within a kind, shortest first.
_DROP_KIND_ORDER: tuple[PauseHoldKind, ...] = (
    PauseHoldKind.OTHER,
    PauseHoldKind.PRACTICE,
    PauseHoldKind.SECTION,
    PauseHoldKind.INTEGRATION,
)


def clamp_hold_seconds(seconds: int, kind: PauseHoldKind) -> int:
    """Clamp a hold duration into the approved range for its kind."""
    bounds = KIND_BOUNDS[kind]
    clamped = max(bounds.min_seconds, min(bounds.max_seconds, int(seconds)))
    return max(MIN_HOLD_SECONDS, min(MAX_HOLD_SECONDS, clamped))


def jitter_hold_seconds(hold_id: str, seconds: int, *, ratio: float = HOLD_JITTER_RATIO) -> int:
    """Perturb ``seconds`` by up to ``ratio`` in either direction, seeded on ``hold_id``.

    Deterministic: the same ``hold_id`` + ``seconds`` always jitters the same way,
    so replays of an already-persisted plan never drift (see ``PausePlanStore``
    reuse semantics in ``service.py``).
    """
    rng = random.Random(hold_id)
    factor = 1.0 + rng.uniform(-ratio, ratio)
    return max(1, round(seconds * factor))


def normalize_pause_plan(
    plan: PausePlan,
    *,
    target_duration_seconds: int | None = None,
    estimated_speech_seconds: int | None = None,
    tail_estimate_seconds: int = DEFAULT_TAIL_ESTIMATE_SECONDS,
) -> PausePlan:
    """Clamp holds, enforce duration budget, and recompute totals.

    Uses ``target_duration_seconds`` / ``estimated_speech_seconds`` arguments when
    provided; otherwise falls back to values already on ``plan``.
    """
    target = (
        target_duration_seconds
        if target_duration_seconds is not None
        else plan.target_duration_seconds
    )
    speech = (
        estimated_speech_seconds
        if estimated_speech_seconds is not None
        else plan.estimated_speech_seconds
    )
    tail = max(0, int(tail_estimate_seconds))

    holds = [
        hold.model_copy(
            update={
                "hold_seconds": clamp_hold_seconds(
                    jitter_hold_seconds(hold.hold_id, hold.hold_seconds),
                    hold.kind,
                )
            }
        )
        for hold in plan.holds
    ]

    holds = _enforce_max_hold_count(holds)
    holds = _fit_holds_to_budget(
        holds,
        target_duration_seconds=target,
        estimated_speech_seconds=speech,
        tail_estimate_seconds=tail,
    )
    holds = _expand_holds_toward_budget(
        holds,
        target_duration_seconds=target,
        estimated_speech_seconds=speech,
        tail_estimate_seconds=tail,
    )

    return plan.model_copy(
        update={
            "holds": holds,
            "total_hold_seconds": sum(h.hold_seconds for h in holds),
            "target_duration_seconds": target,
            "estimated_speech_seconds": speech,
            "policy_version": PAUSE_POLICY_VERSION,
            "prompt_version": plan.prompt_version or PROMPT_VERSION,
        }
    )


def validate_pause_plan_anchors(
    plan: PausePlan,
    *,
    beat_count: int,
    paragraph_count: int,
) -> None:
    """Ensure every hold anchor is in range for the transcript anchors."""
    if beat_count < 0 or paragraph_count < 0:
        raise PausePlannerError("beat_count and paragraph_count must be >= 0")

    for hold in plan.holds:
        if hold.after_beat_index is not None:
            if beat_count <= 0:
                raise PausePlannerError(
                    f"hold {hold.hold_id!r} uses after_beat_index but beat_count is 0"
                )
            if hold.after_beat_index >= beat_count:
                raise PausePlannerError(
                    f"hold {hold.hold_id!r} after_beat_index={hold.after_beat_index} "
                    f"out of range for beat_count={beat_count}"
                )
        if hold.after_paragraph_index is not None:
            if paragraph_count <= 0:
                raise PausePlannerError(
                    f"hold {hold.hold_id!r} uses after_paragraph_index but paragraph_count is 0"
                )
            if hold.after_paragraph_index >= paragraph_count:
                raise PausePlannerError(
                    f"hold {hold.hold_id!r} after_paragraph_index={hold.after_paragraph_index} "
                    f"out of range for paragraph_count={paragraph_count}"
                )


def _ideal_hold_budget_seconds(
    *,
    target_duration_seconds: int | None,
    estimated_speech_seconds: int | None,
    tail_estimate_seconds: int,
) -> int | None:
    if target_duration_seconds is None or estimated_speech_seconds is None:
        return None
    return max(0, int(target_duration_seconds) - int(estimated_speech_seconds) - int(tail_estimate_seconds))


def _expand_holds_toward_budget(
    holds: list[PauseHold],
    *,
    target_duration_seconds: int | None,
    estimated_speech_seconds: int | None,
    tail_estimate_seconds: int,
) -> list[PauseHold]:
    """Scale holds up when they undershoot the ideal hold room inside wall-clock."""
    if not holds:
        return holds
    ideal = _ideal_hold_budget_seconds(
        target_duration_seconds=target_duration_seconds,
        estimated_speech_seconds=estimated_speech_seconds,
        tail_estimate_seconds=tail_estimate_seconds,
    )
    if ideal is None or ideal <= 0:
        return holds

    current = sum(h.hold_seconds for h in holds)
    if current <= 0:
        return holds
    if current >= ideal * HOLD_UNDERFILL_EXPAND_RATIO:
        return holds

    scale = ideal / current
    expanded: list[PauseHold] = []
    for hold in holds:
        raw = max(1, int(math.ceil(hold.hold_seconds * scale)))
        expanded.append(
            hold.model_copy(update={"hold_seconds": clamp_hold_seconds(raw, hold.kind)})
        )

    # Re-fit in case expansion hit kind maxes and still sits under/over.
    fitted = _fit_holds_to_budget(
        expanded,
        target_duration_seconds=target_duration_seconds,
        estimated_speech_seconds=estimated_speech_seconds,
        tail_estimate_seconds=tail_estimate_seconds,
    )
    logger.info(
        "pause plan expanded holds toward budget before=%ss after=%ss ideal=%ss",
        current,
        sum(h.hold_seconds for h in fitted),
        ideal,
    )
    return fitted


def _budget_limit_seconds(target_duration_seconds: int | None) -> int | None:
    if target_duration_seconds is None:
        return None
    return int(math.floor(target_duration_seconds * (1.0 + DURATION_TOLERANCE_RATIO)))


def _holds_over_budget(
    holds: list[PauseHold],
    *,
    target_duration_seconds: int | None,
    estimated_speech_seconds: int | None,
    tail_estimate_seconds: int,
) -> bool:
    limit = _budget_limit_seconds(target_duration_seconds)
    if limit is None or estimated_speech_seconds is None:
        return False
    total = estimated_speech_seconds + sum(h.hold_seconds for h in holds) + tail_estimate_seconds
    return total > limit


def _fit_holds_to_budget(
    holds: list[PauseHold],
    *,
    target_duration_seconds: int | None,
    estimated_speech_seconds: int | None,
    tail_estimate_seconds: int,
) -> list[PauseHold]:
    if not _holds_over_budget(
        holds,
        target_duration_seconds=target_duration_seconds,
        estimated_speech_seconds=estimated_speech_seconds,
        tail_estimate_seconds=tail_estimate_seconds,
    ):
        return holds

    assert target_duration_seconds is not None
    assert estimated_speech_seconds is not None
    limit = _budget_limit_seconds(target_duration_seconds)
    assert limit is not None

    available_for_holds = limit - estimated_speech_seconds - tail_estimate_seconds
    if available_for_holds <= 0:
        # Speech alone already fills (or exceeds) wall-clock. Still keep short
        # density holds — empty pause plans make Script Hub / TTS sound like a lecture.
        logger.warning(
            "pause plan budget has no room for holds; keeping prefer-min holds "
            "target=%s speech=%s tail=%s hold_count=%s",
            target_duration_seconds,
            estimated_speech_seconds,
            tail_estimate_seconds,
            len(holds),
        )
        return [
            hold.model_copy(
                update={
                    "hold_seconds": clamp_hold_seconds(
                        KIND_BOUNDS[hold.kind].prefer_min,
                        hold.kind,
                    )
                }
            )
            for hold in holds
        ]

    current_total = sum(h.hold_seconds for h in holds)
    if current_total <= 0:
        return holds

    scale = available_for_holds / current_total
    scaled: list[PauseHold] = []
    for hold in holds:
        raw = max(1, int(math.floor(hold.hold_seconds * scale)))
        scaled.append(
            hold.model_copy(update={"hold_seconds": clamp_hold_seconds(raw, hold.kind)})
        )

    if not _holds_over_budget(
        scaled,
        target_duration_seconds=target_duration_seconds,
        estimated_speech_seconds=estimated_speech_seconds,
        tail_estimate_seconds=tail_estimate_seconds,
    ):
        logger.info(
            "pause plan scaled holds to fit budget before=%ss after=%ss available=%ss",
            current_total,
            sum(h.hold_seconds for h in scaled),
            available_for_holds,
        )
        return scaled

    # Already at prefer-min after scale/clamp — keep sentence density rather than
    # stripping silence back to a lecture. Wall-clock may exceed the target.
    prefer_min_only = [
        hold.model_copy(
            update={
                "hold_seconds": clamp_hold_seconds(
                    KIND_BOUNDS[hold.kind].prefer_min,
                    hold.kind,
                )
            }
        )
        for hold in scaled
    ]
    if _holds_over_budget(
        prefer_min_only,
        target_duration_seconds=target_duration_seconds,
        estimated_speech_seconds=estimated_speech_seconds,
        tail_estimate_seconds=tail_estimate_seconds,
    ):
        logger.warning(
            "pause plan keeps prefer-min density holds over wall-clock "
            "target=%s speech=%s hold_count=%s total_hold=%ss",
            target_duration_seconds,
            estimated_speech_seconds,
            len(prefer_min_only),
            sum(h.hold_seconds for h in prefer_min_only),
        )
        return prefer_min_only

    trimmed = list(scaled)
    while trimmed and _holds_over_budget(
        trimmed,
        target_duration_seconds=target_duration_seconds,
        estimated_speech_seconds=estimated_speech_seconds,
        tail_estimate_seconds=tail_estimate_seconds,
    ):
        drop_index = _lowest_priority_hold_index(trimmed)
        dropped = trimmed.pop(drop_index)
        logger.warning(
            "pause plan dropped hold %s kind=%s seconds=%s to fit duration budget",
            dropped.hold_id,
            dropped.kind.value,
            dropped.hold_seconds,
        )
    return trimmed


def _lowest_priority_hold_index(holds: list[PauseHold]) -> int:
    best_index = 0
    best_key: tuple[int, int, int] | None = None
    for index, hold in enumerate(holds):
        kind_rank = _DROP_KIND_ORDER.index(hold.kind)
        key = (kind_rank, hold.hold_seconds, index)
        if best_key is None or key < best_key:
            best_key = key
            best_index = index
    return best_index


def _enforce_max_hold_count(holds: list[PauseHold]) -> list[PauseHold]:
    if len(holds) <= MAX_HOLDS_PER_JOB:
        return holds
    trimmed = list(holds)
    while len(trimmed) > MAX_HOLDS_PER_JOB:
        drop_index = _lowest_priority_hold_index(trimmed)
        dropped = trimmed.pop(drop_index)
        logger.warning(
            "pause plan dropped hold %s to enforce MAX_HOLDS_PER_JOB=%s",
            dropped.hold_id,
            MAX_HOLDS_PER_JOB,
        )
    return trimmed
