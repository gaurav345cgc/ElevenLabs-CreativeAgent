"""Human Script Hub pause markers — parse, format, and build PausePlan."""

from __future__ import annotations

import pytest

from tts_pipeline.pause_planner.human_markers import (
    DEFAULT_HUMAN_PAUSE_SECONDS,
    HUMAN_PAUSE_PLAN_KEY,
    HUMAN_PROMPT_VERSION,
    HumanPauseMarkerError,
    build_human_pause_plan,
    build_pause_review_text,
    format_pause_marked_text,
    load_human_pause_plan,
    parse_pause_marked_text,
)
from tts_pipeline.pause_planner.policy import PAUSE_POLICY_VERSION
from tts_pipeline.pause_planner.schema import PauseHoldKind, PausePlannerProvider


SAMPLE = """\
Welcome to this guided meditation journey.

In the next few moments, we will explore a space of calm.

[pause 8s]

Allow this time to be yours, no expectations, no pressure.

Here, you can embrace the stillness.

[pause]

Give yourself permission to simply be.
"""


def test_parse_pause_marked_text_with_seconds() -> None:
    parsed = parse_pause_marked_text(SAMPLE)
    assert len(parsed.speech_units) == 5
    assert parsed.speech_units[0].startswith("Welcome")
    assert len(parsed.holds) == 2
    assert parsed.holds[0].after_beat_index == 1
    assert parsed.holds[0].hold_seconds == 8
    assert parsed.holds[1].after_beat_index == 3
    assert parsed.holds[1].hold_seconds == DEFAULT_HUMAN_PAUSE_SECONDS
    assert "[pause" not in parsed.spoken_text
    assert "Allow this time" in parsed.spoken_text


def test_parse_rejects_leading_pause() -> None:
    with pytest.raises(HumanPauseMarkerError, match="before the first"):
        parse_pause_marked_text("[pause 5s]\n\nHello there.")


def test_round_trip_format() -> None:
    parsed = parse_pause_marked_text(SAMPLE)
    rendered = format_pause_marked_text(parsed.speech_units, parsed.holds)
    again = parse_pause_marked_text(rendered)
    assert again.speech_units == parsed.speech_units
    assert [h.hold_seconds for h in again.holds] == [h.hold_seconds for h in parsed.holds]
    assert [h.after_beat_index for h in again.holds] == [h.after_beat_index for h in parsed.holds]


def test_build_human_pause_plan() -> None:
    parsed = parse_pause_marked_text(SAMPLE)
    plan = build_human_pause_plan(parsed, target_duration_seconds=300)
    assert plan.planner is PausePlannerProvider.HUMAN
    assert plan.model == "human-reviewer"
    assert plan.prompt_version == HUMAN_PROMPT_VERSION
    assert plan.policy_version == PAUSE_POLICY_VERSION
    assert plan.total_hold_seconds == 8 + DEFAULT_HUMAN_PAUSE_SECONDS
    assert all(h.kind is PauseHoldKind.PRACTICE for h in plan.holds)


def test_build_pause_review_text_from_beats_without_plan() -> None:
    text = build_pause_review_text(
        content_text="ignored when beats exist",
        content_json={"beats": ["One.", "Two.", "Three."]},
        metadata_json={},
    )
    assert text == "One.\n\nTwo.\n\nThree."
    assert "[pause" not in text


def test_build_pause_review_text_with_saved_plan() -> None:
    parsed = parse_pause_marked_text("One.\n\n[pause 7s]\n\nTwo.")
    plan = build_human_pause_plan(parsed)
    text = build_pause_review_text(
        content_text=parsed.spoken_text,
        content_json={"beats": parsed.speech_units},
        metadata_json={HUMAN_PAUSE_PLAN_KEY: plan.model_dump(mode="json")},
    )
    assert "[pause 7s]" in text
    assert load_human_pause_plan({HUMAN_PAUSE_PLAN_KEY: plan.model_dump(mode="json")}) is not None


def test_build_pause_review_text_with_draft_plan() -> None:
    from tts_pipeline.pause_planner.human_markers import DRAFT_PAUSE_PLAN_KEY

    parsed = parse_pause_marked_text("One.\n\n[pause 9s]\n\nTwo.")
    plan = build_human_pause_plan(parsed)
    # Draft uses same PausePlan shape; render path prefers human only when holds exist
    # under human key — draft key should still show markers.
    text = build_pause_review_text(
        content_text=parsed.spoken_text,
        content_json={"beats": parsed.speech_units},
        metadata_json={DRAFT_PAUSE_PLAN_KEY: plan.model_dump(mode="json")},
    )
    assert "[pause 9s]" in text


def test_build_pause_review_text_human_overrides_draft() -> None:
    from tts_pipeline.pause_planner.human_markers import DRAFT_PAUSE_PLAN_KEY

    draft = build_human_pause_plan(parse_pause_marked_text("A.\n\n[pause 9s]\n\nB."))
    human = build_human_pause_plan(parse_pause_marked_text("A.\n\n[pause 4s]\n\nB."))
    text = build_pause_review_text(
        content_text="A.\n\nB.",
        content_json={"beats": ["A.", "B."]},
        metadata_json={
            DRAFT_PAUSE_PLAN_KEY: draft.model_dump(mode="json"),
            HUMAN_PAUSE_PLAN_KEY: human.model_dump(mode="json"),
        },
    )
    assert "[pause 4s]" in text
    assert "[pause 9s]" not in text
