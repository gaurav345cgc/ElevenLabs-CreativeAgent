"""PlanPauses prefers Script Hub human_pause_plan over OpenAI."""

from __future__ import annotations

from types import SimpleNamespace

from tts_pipeline.orchestrator import states as states_module
from tts_pipeline.pause_planner.anchors import PauseAnchors
from tts_pipeline.pause_planner.human_markers import (
    HUMAN_PAUSE_PLAN_KEY,
    build_human_pause_plan,
    parse_pause_marked_text,
)
from tts_pipeline.pause_planner.schema import PausePlannerProvider


def test_plan_factory_uses_human_plan_and_skips_openai() -> None:
    parsed = parse_pause_marked_text("Beat one.\n\n[pause 6s]\n\nBeat two.\n\nBeat three.")
    human = build_human_pause_plan(parsed)
    version = SimpleNamespace(
        metadata_json={HUMAN_PAUSE_PLAN_KEY: human.model_dump(mode="json")}
    )
    anchors = PauseAnchors(
        beats=list(parsed.speech_units),
        paragraphs=list(parsed.speech_units),
        preferred="beats",
    )

    factory = states_module._build_plan_factory(
        version=version,
        anchors=anchors,
        target_duration_seconds=300,
        estimated_speech_seconds=120,
        pause_planner_client=None,
    )
    plan = factory()
    assert plan.planner is PausePlannerProvider.HUMAN
    assert any(h.hold_seconds == 6 for h in plan.holds)
    assert plan.target_duration_seconds == 300
