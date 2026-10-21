"""Phase 1 stub: pause plan schema round-trip and validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tts_pipeline.pause_planner import (
    MappedPauseHold,
    MappedPausePlan,
    PauseHold,
    PauseHoldKind,
    PausePlan,
    PausePlannerProvider,
)


def test_pause_plan_json_round_trip() -> None:
    plan = PausePlan(
        planner=PausePlannerProvider.OPENAI,
        model="gpt-4o-mini",
        prompt_version="pause-prompt-v1",
        policy_version="pause-v1",
        target_duration_seconds=600,
        estimated_speech_seconds=420,
        total_hold_seconds=0,  # recomputed from holds
        holds=[
            PauseHold(
                hold_id="h1",
                after_beat_index=3,
                hold_seconds=12,
                kind=PauseHoldKind.PRACTICE,
                reason="Listener needs time to soften shoulders",
            ),
            PauseHold(
                hold_id="h2",
                after_beat_index=11,
                hold_seconds=45,
                kind=PauseHoldKind.INTEGRATION,
                reason="Rest before closing",
            ),
        ],
    )
    assert plan.total_hold_seconds == 57

    payload = plan.model_dump(mode="json")
    restored = PausePlan.model_validate(payload)
    assert restored == plan
    assert restored.holds[0].kind == PauseHoldKind.PRACTICE


def test_pause_hold_requires_exactly_one_anchor() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        PauseHold(
            hold_id="h1",
            after_beat_index=1,
            after_paragraph_index=1,
            hold_seconds=10,
            kind=PauseHoldKind.PRACTICE,
            reason="bad dual anchor",
        )
    with pytest.raises(ValidationError, match="exactly one"):
        PauseHold(
            hold_id="h1",
            hold_seconds=10,
            kind=PauseHoldKind.PRACTICE,
            reason="missing anchor",
        )


def test_pause_plan_rejects_duplicate_hold_ids() -> None:
    with pytest.raises(ValidationError, match="unique"):
        PausePlan(
            planner=PausePlannerProvider.OPENAI,
            model="gpt-4o-mini",
            prompt_version="pause-prompt-v1",
            policy_version="pause-v1",
            total_hold_seconds=20,
            holds=[
                PauseHold(
                    hold_id="h1",
                    after_beat_index=0,
                    hold_seconds=10,
                    kind=PauseHoldKind.PRACTICE,
                    reason="first",
                ),
                PauseHold(
                    hold_id="h1",
                    after_beat_index=1,
                    hold_seconds=10,
                    kind=PauseHoldKind.SECTION,
                    reason="duplicate id",
                ),
            ],
        )


def test_mapped_pause_plan_json_round_trip() -> None:
    mapped = MappedPausePlan(
        total_hold_seconds=12,
        holds=[
            MappedPauseHold(
                hold_id="h1",
                after_beat_index=3,
                after_chunk_index=1,
                hold_seconds=12,
                kind=PauseHoldKind.PRACTICE,
                reason="absorb cue",
            )
        ],
    )
    restored = MappedPausePlan.model_validate(mapped.model_dump(mode="json"))
    assert restored == mapped
    assert restored.holds[0].after_chunk_index == 1
