"""Phase 2: pause policy clamps and duration budgeting."""

from __future__ import annotations

import pytest

from tts_pipeline.pause_planner.errors import PausePlannerError
from tts_pipeline.pause_planner.policy import (
    DEFAULT_FAIL_ON_PLANNER_ERROR,
    DURATION_TOLERANCE_RATIO,
    HOLD_JITTER_RATIO,
    KIND_BOUNDS,
    MAX_HOLD_SECONDS,
    MAX_HOLDS_PER_JOB,
    MIN_HOLD_SECONDS,
    PAUSE_POLICY_VERSION,
    PROMPT_VERSION,
    clamp_hold_seconds,
    jitter_hold_seconds,
    normalize_pause_plan,
    validate_pause_plan_anchors,
)
from tts_pipeline.pause_planner.schema import (
    PauseHold,
    PauseHoldKind,
    PausePlan,
    PausePlannerProvider,
)


def _plan(holds: list[PauseHold], *, target: int | None = 600, speech: int | None = 420) -> PausePlan:
    return PausePlan(
        planner=PausePlannerProvider.OPENAI,
        model="gpt-4o-mini",
        prompt_version=PROMPT_VERSION,
        policy_version=PAUSE_POLICY_VERSION,
        target_duration_seconds=target,
        estimated_speech_seconds=speech,
        total_hold_seconds=0,
        holds=holds,
    )


def _hold(
    hold_id: str,
    seconds: int,
    kind: PauseHoldKind,
    *,
    beat: int = 0,
) -> PauseHold:
    return PauseHold(
        hold_id=hold_id,
        after_beat_index=beat,
        hold_seconds=seconds,
        kind=kind,
        reason=f"reason for {hold_id}",
    )


def test_policy_constants() -> None:
    assert PAUSE_POLICY_VERSION == "pause-v7"
    assert PROMPT_VERSION == "pause-prompt-v7"
    assert MIN_HOLD_SECONDS == 2
    assert MAX_HOLD_SECONDS == 90
    assert MAX_HOLDS_PER_JOB == 150
    assert DURATION_TOLERANCE_RATIO == 0.10
    assert DEFAULT_FAIL_ON_PLANNER_ERROR is True
    assert KIND_BOUNDS[PauseHoldKind.PRACTICE].min_seconds == 2
    assert KIND_BOUNDS[PauseHoldKind.PRACTICE].max_seconds == 12
    assert KIND_BOUNDS[PauseHoldKind.SECTION].min_seconds == 8
    assert KIND_BOUNDS[PauseHoldKind.SECTION].max_seconds == 30
    assert KIND_BOUNDS[PauseHoldKind.INTEGRATION].min_seconds == 15
    assert KIND_BOUNDS[PauseHoldKind.INTEGRATION].max_seconds == 75


def test_clamp_hold_seconds_by_kind() -> None:
    assert clamp_hold_seconds(1, PauseHoldKind.PRACTICE) == 2
    assert clamp_hold_seconds(100, PauseHoldKind.PRACTICE) == 12
    assert clamp_hold_seconds(10, PauseHoldKind.PRACTICE) == 10
    assert clamp_hold_seconds(5, PauseHoldKind.SECTION) == 8
    assert clamp_hold_seconds(50, PauseHoldKind.SECTION) == 30
    assert clamp_hold_seconds(10, PauseHoldKind.INTEGRATION) == 15
    assert clamp_hold_seconds(120, PauseHoldKind.INTEGRATION) == 75


def test_normalize_clamps_and_recomputes_total() -> None:
    plan = _plan(
        [
            _hold("h1", 2, PauseHoldKind.PRACTICE, beat=0),
            _hold("h2", 100, PauseHoldKind.INTEGRATION, beat=1),
        ],
        target=None,
        speech=None,
    )
    normalized = normalize_pause_plan(plan)
    assert normalized.holds[0].hold_seconds == 2
    assert normalized.holds[1].hold_seconds == 75
    assert normalized.total_hold_seconds == 77
    assert normalized.policy_version == PAUSE_POLICY_VERSION


def test_normalize_expands_holds_when_under_budget() -> None:
    # Ideal hold room ≈ 600 - 420 - 4 = 176; two short holds should scale up.
    plan = _plan(
        [
            _hold("h1", 5, PauseHoldKind.PRACTICE, beat=0),
            _hold("h2", 5, PauseHoldKind.SECTION, beat=1),
            _hold("h3", 20, PauseHoldKind.INTEGRATION, beat=2),
        ],
        target=600,
        speech=420,
    )
    before = sum(h.hold_seconds for h in plan.holds)
    normalized = normalize_pause_plan(plan, tail_estimate_seconds=4)
    assert normalized.total_hold_seconds > before
    # Still within wall-clock tolerance band.
    limit = int(600 * (1.0 + DURATION_TOLERANCE_RATIO))
    assert 420 + normalized.total_hold_seconds + 4 <= limit


def test_normalize_keeps_min_holds_when_speech_exceeds_target() -> None:
    """Over-long narration must not wipe silence — density holds stay at prefer-min."""
    plan = _plan(
        [
            _hold("h1", 10, PauseHoldKind.PRACTICE, beat=0),
            _hold("h2", 12, PauseHoldKind.PRACTICE, beat=1),
            _hold("h3", 30, PauseHoldKind.SECTION, beat=2),
        ],
        target=300,
        speech=374,
    )
    normalized = normalize_pause_plan(plan, tail_estimate_seconds=4)
    assert len(normalized.holds) == 3
    assert all(h.hold_seconds >= MIN_HOLD_SECONDS for h in normalized.holds)
    assert normalized.holds[0].hold_seconds == KIND_BOUNDS[PauseHoldKind.PRACTICE].prefer_min
    assert normalized.holds[2].hold_seconds == KIND_BOUNDS[PauseHoldKind.SECTION].prefer_min


def test_normalize_scales_down_when_over_budget() -> None:
    # speech 80 + holds 40 + tail 4 must fit target*tolerance
    plan = _plan(
        [
            _hold("h1", 20, PauseHoldKind.PRACTICE, beat=0),
            _hold("h2", 20, PauseHoldKind.PRACTICE, beat=1),
        ],
        target=100,
        speech=80,
    )
    normalized = normalize_pause_plan(plan, tail_estimate_seconds=4)
    limit = int(100 * (1.0 + DURATION_TOLERANCE_RATIO))
    total = 80 + normalized.total_hold_seconds + 4
    assert total <= limit
    assert normalized.total_hold_seconds < 40
    assert all(h.hold_seconds >= MIN_HOLD_SECONDS for h in normalized.holds)


def test_normalize_keeps_prefer_min_density_when_still_over() -> None:
    # After clamp-to-min, still over wall-clock — keep sentence density (no wipe).
    plan = _plan(
        [
            _hold("other1", 10, PauseHoldKind.OTHER, beat=0),
            _hold("prac1", 10, PauseHoldKind.PRACTICE, beat=1),
        ],
        target=50,
        speech=50,
    )
    normalized = normalize_pause_plan(plan, tail_estimate_seconds=4)
    assert len(normalized.holds) == 2
    assert all(h.hold_seconds == KIND_BOUNDS[h.kind].prefer_min for h in normalized.holds)


def test_jitter_is_deterministic_per_hold_id() -> None:
    first = jitter_hold_seconds("h1", 20)
    second = jitter_hold_seconds("h1", 20)
    assert first == second


def test_jitter_stays_within_ratio_bounds() -> None:
    seconds = 20
    for hold_id in [f"h{i}" for i in range(50)]:
        jittered = jitter_hold_seconds(hold_id, seconds)
        assert abs(jittered - seconds) <= round(seconds * HOLD_JITTER_RATIO) + 1


def test_jitter_is_not_degenerate_across_hold_ids() -> None:
    values = {jitter_hold_seconds(f"h{i}", 20) for i in range(50)}
    assert len(values) > 1


def test_jitter_never_produces_less_than_one_second() -> None:
    assert jitter_hold_seconds("any", 1) >= 1


def test_validate_pause_plan_anchors() -> None:
    plan = _plan([_hold("h1", 10, PauseHoldKind.PRACTICE, beat=2)])
    validate_pause_plan_anchors(plan, beat_count=3, paragraph_count=0)

    with pytest.raises(PausePlannerError, match="out of range"):
        validate_pause_plan_anchors(plan, beat_count=2, paragraph_count=0)

    paragraph_plan = PausePlan(
        planner=PausePlannerProvider.OPENAI,
        model="gpt-4o-mini",
        prompt_version=PROMPT_VERSION,
        policy_version=PAUSE_POLICY_VERSION,
        total_hold_seconds=10,
        holds=[
            PauseHold(
                hold_id="p1",
                after_paragraph_index=1,
                hold_seconds=10,
                kind=PauseHoldKind.SECTION,
                reason="section break",
            )
        ],
    )
    with pytest.raises(PausePlannerError, match="paragraph"):
        validate_pause_plan_anchors(paragraph_plan, beat_count=0, paragraph_count=1)
