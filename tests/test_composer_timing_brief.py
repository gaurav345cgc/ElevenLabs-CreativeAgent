"""Composer session timing brief and slot word ceilings."""

from __future__ import annotations

from models.duration_budget import build_session_duration_budget
from transcript_composer.duration import (
    MIN_SLOT_WORD_CEILING,
    clamp_slot_word_ceiling,
    format_composer_timing_brief,
)
from transcript_composer.script_generator import _target_words_for_slot
from models.validation import COMPOSITION_SLOTS


def test_format_composer_timing_brief_five_minute_numbers() -> None:
    budget = build_session_duration_budget(5)
    assert budget.target_duration_seconds == 300
    assert budget.speech_budget_seconds == 186
    assert budget.hold_budget_seconds == 114
    assert budget.speech_budget_words == 403

    brief = format_composer_timing_brief(
        budget,
        slot="settling",
        slot_word_ceiling=70,
        words_used_so_far=40,
    )
    assert "300s" in brief
    assert "403" in brief
    assert "186s" in brief
    assert "114s" in brief
    assert "≤ 70 words" in brief
    assert "40 / 403" in brief
    assert "remaining for all later speech: 363" in brief
    assert "do NOT write" in brief
    assert "silence is planned downstream" in brief


def test_clamp_slot_word_ceiling_to_remaining() -> None:
    assert clamp_slot_word_ceiling(80, 50) == 50
    assert clamp_slot_word_ceiling(80, 200) == 80
    assert clamp_slot_word_ceiling(80, 0) == MIN_SLOT_WORD_CEILING
    assert clamp_slot_word_ceiling(80, 10) == MIN_SLOT_WORD_CEILING


def test_slot_ceilings_sum_near_speech_budget() -> None:
    budget = build_session_duration_budget(5)
    total = sum(_target_words_for_slot(5, slot) for slot in COMPOSITION_SLOTS)
    # Opening is brief; body slots share remaining — total should be near speech budget.
    assert abs(total - budget.speech_budget_words) <= budget.speech_budget_words * 0.15
