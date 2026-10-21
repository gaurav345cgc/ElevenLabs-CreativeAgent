"""Phase 4: pause planner prompts and response parsing."""

from __future__ import annotations

import json

import pytest

from tts_pipeline.pause_planner.errors import PausePlannerValidationError
from tts_pipeline.pause_planner.policy import PAUSE_POLICY_VERSION, PROMPT_VERSION
from tts_pipeline.pause_planner.prompt import (
    build_system_prompt,
    build_user_prompt,
    parse_pause_plan_response,
)
from tts_pipeline.pause_planner.schema import PauseHoldKind, PausePlannerProvider


def test_system_prompt_references_prompt_version() -> None:
    text = build_system_prompt()
    assert "meditation pause planner" in text.lower()
    assert PROMPT_VERSION in text
    assert PAUSE_POLICY_VERSION in text
    assert "Do NOT rewrite" in text or "Do NOT rewrite" in text.replace("do not", "Do NOT")
    assert "after_beat_index" in text
    assert "after_paragraph_index" in text
    assert "json" in text.lower()
    assert "frequent" in text.lower() or "nearly every" in text.lower()
    assert "3" in text and ("sentence" in text.lower() or "sentences" in text.lower())
    assert "flood" in text.lower() or "wall of uninterrupted" in text.lower() or "lecture" in text.lower()


def test_user_prompt_beats_numbered_and_budget() -> None:
    user = build_user_prompt(
        beats=["Opening line.", "Let your shoulders soften."],
        paragraphs=[],
        target_duration_seconds=600,
        estimated_speech_seconds=420,
    )
    assert "target_duration_seconds (WALL-CLOCK including holds): 600" in user
    assert "estimated_speech_seconds: 420" in user
    assert "hold_budget_seconds" in user
    assert "TIMING CONTRACT" in user
    assert "180" in user  # 600 - 420
    assert "0: Opening line." in user
    assert "1: Let your shoulders soften." in user
    assert "after_beat_index only" in user
    assert "Good vs bad placement" in user
    assert "practice" in user
    assert "3 spoken sentences" in user or "HARD DENSITY" in user


def test_user_prompt_paragraphs_when_no_beats() -> None:
    user = build_user_prompt(
        beats=[],
        paragraphs=["Para one.", "Para two."],
        target_duration_seconds=300,
        estimated_speech_seconds=200,
    )
    assert "after_paragraph_index only" in user
    assert "0: Para one." in user
    assert "Policy bounds by kind" in user


def test_parse_pause_plan_response_server_side_metadata() -> None:
    raw = {
        "holds": [
            {
                "hold_id": "h1",
                "after_beat_index": 3,
                "hold_seconds": 12,
                "kind": "practice",
                "reason": "Time to soften shoulders",
            }
        ],
        "planner": "should-be-ignored",
        "model": "should-be-ignored",
    }
    body = json.dumps(raw).encode("utf-8")
    plan = parse_pause_plan_response(
        raw,
        model="gpt-4o-mini",
        target_duration_seconds=600,
        estimated_speech_seconds=420,
        raw_response_bytes=body,
        use_beats=True,
    )
    assert plan.planner == PausePlannerProvider.OPENAI
    assert plan.model == "gpt-4o-mini"
    assert plan.prompt_version == PROMPT_VERSION
    assert plan.policy_version == PAUSE_POLICY_VERSION
    assert plan.total_hold_seconds == 12
    assert plan.holds[0].after_beat_index == 3
    assert plan.holds[0].kind == PauseHoldKind.PRACTICE
    assert plan.raw_response_sha256 is not None
    assert len(plan.raw_response_sha256) == 64


def test_parse_coerces_paragraph_index_when_beats_mode() -> None:
    raw = {
        "holds": [
            {
                "hold_id": "h1",
                "after_paragraph_index": 2,
                "hold_seconds": 15,
                "kind": "section",
                "reason": "Section rest",
            }
        ]
    }
    plan = parse_pause_plan_response(
        raw,
        model="gpt-4o-mini",
        target_duration_seconds=600,
        estimated_speech_seconds=400,
        use_beats=True,
    )
    assert plan.holds[0].after_beat_index == 2
    assert plan.holds[0].after_paragraph_index is None


def test_parse_rejects_invalid_holds_shape() -> None:
    with pytest.raises(PausePlannerValidationError, match="array"):
        parse_pause_plan_response(
            {"holds": "nope"},
            model="m",
            target_duration_seconds=100,
            estimated_speech_seconds=80,
            use_beats=True,
        )
