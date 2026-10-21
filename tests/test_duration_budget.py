"""Shared speech/hold duration budget for Agent 1 + pause planner."""

from __future__ import annotations

from models.duration_budget import (
    DEFAULT_SPEECH_SHARE,
    build_session_duration_budget,
    copy_duration_budget_metadata,
)
from transcript_composer.script_generator import _target_words_for_slot, _target_words_per_section


def test_ten_minute_budget_splits_speech_and_holds() -> None:
    budget = build_session_duration_budget(10)
    assert budget.target_duration_seconds == 600
    assert budget.speech_share == DEFAULT_SPEECH_SHARE
    assert budget.speech_budget_seconds + budget.hold_budget_seconds == 600
    assert budget.speech_budget_seconds == 372  # 0.62 * 600
    assert budget.hold_budget_seconds == 228
    assert budget.speech_budget_words == 806  # 372/60 * 130


def test_agent1_word_targets_use_speech_budget_not_full_wall_clock() -> None:
    full_words = int(round(10 * 130))  # old wall-clock word sizing
    speech_words = build_session_duration_budget(10).speech_budget_words
    assert speech_words < full_words
    opening = _target_words_for_slot(10, "opening")
    body = _target_words_per_section(10)
    assert opening <= 70
    assert body < full_words // 5


def test_copy_duration_budget_metadata_filters_keys() -> None:
    copied = copy_duration_budget_metadata(
        {
            "target_duration_minutes": 5,
            "hold_budget_seconds": 84,
            "unrelated": "x",
            "speech_share": None,
        }
    )
    assert copied == {
        "target_duration_minutes": 5,
        "hold_budget_seconds": 84,
    }
