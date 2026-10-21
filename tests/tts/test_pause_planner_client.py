"""Phase 5: mocked OpenAI → parse → normalize integration tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

from tts_pipeline.pause_planner import (
    OpenAIPausePlannerClient,
    normalize_pause_plan,
    parse_pause_plan_response,
    validate_pause_plan_anchors,
)
from tts_pipeline.pause_planner.schema import PauseHoldKind, PausePlannerProvider


def _response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def test_mock_openai_returns_holds_then_parse_and_normalize_succeeds() -> None:
    """End-to-end Slice 1 path without live API: client → PausePlan → normalized plan."""
    payload = {
        "holds": [
            {
                "hold_id": "h1",
                "after_beat_index": 0,
                "hold_seconds": 200,
                "kind": "practice",
                "reason": "absorb cue",
            },
            {
                "hold_id": "h2",
                "after_beat_index": 1,
                "hold_seconds": 100,
                "kind": "integration",
                "reason": "rest before close",
            },
        ]
    }

    client = OpenAIPausePlannerClient(
        create_completion=lambda **_: _response(json.dumps(payload)),
        model="gpt-4o-mini",
    )
    raw = client.plan_pauses(
        beats=["Let your shoulders soften.", "When you are ready, return gently."],
        paragraphs=[],
        target_duration_seconds=600,
        estimated_speech_seconds=420,
    )

    plan = parse_pause_plan_response(
        raw,
        model="gpt-4o-mini",
        target_duration_seconds=600,
        estimated_speech_seconds=420,
        raw_response_bytes=json.dumps(raw).encode("utf-8"),
        use_beats=True,
    )
    assert plan.planner == PausePlannerProvider.OPENAI
    assert len(plan.holds) == 2

    validate_pause_plan_anchors(plan, beat_count=2, paragraph_count=0)

    normalized = normalize_pause_plan(
        plan,
        target_duration_seconds=600,
        estimated_speech_seconds=420,
    )
    assert normalized.total_hold_seconds == sum(h.hold_seconds for h in normalized.holds)
    assert normalized.holds[0].hold_seconds == 15  # practice clamp from 200
    assert normalized.holds[1].hold_seconds == 90  # integration clamp from 100


def test_empty_holds_list_allowed_after_normalize_v1() -> None:
    """v1: planner may return no holds (very short script); normalize accepts empty plan."""
    client = OpenAIPausePlannerClient(
        create_completion=lambda **_: _response('{"holds": []}'),
        model="gpt-4o-mini",
    )
    raw = client.plan_pauses(
        beats=["A single short line."],
        paragraphs=[],
        target_duration_seconds=120,
        estimated_speech_seconds=30,
    )
    plan = parse_pause_plan_response(
        raw,
        model="gpt-4o-mini",
        target_duration_seconds=120,
        estimated_speech_seconds=30,
        use_beats=True,
    )
    assert plan.holds == []
    assert plan.total_hold_seconds == 0

    normalized = normalize_pause_plan(plan)
    assert normalized.holds == []
    assert normalized.total_hold_seconds == 0
