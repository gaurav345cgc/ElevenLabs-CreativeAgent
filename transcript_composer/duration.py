"""Duration estimation for composed transcripts."""

from __future__ import annotations

from models.duration_budget import (
    DEFAULT_HOLD_SHARE,
    DEFAULT_SPEECH_SHARE,
    DEFAULT_WORDS_PER_MINUTE,
    DURATION_TOLERANCE_RATIO,
    SessionDurationBudget,
    budget_from_metadata,
    build_session_duration_budget,
    copy_duration_budget_metadata,
)
from models.metadata import DurationEstimate

__all__ = [
    "DEFAULT_HOLD_SHARE",
    "DEFAULT_SPEECH_SHARE",
    "DEFAULT_WORDS_PER_MINUTE",
    "DURATION_TOLERANCE_RATIO",
    "SessionDurationBudget",
    "budget_from_metadata",
    "build_session_duration_budget",
    "clamp_slot_word_ceiling",
    "copy_duration_budget_metadata",
    "count_words",
    "estimate_duration_seconds",
    "format_composer_timing_brief",
]

# Floor so a late section still gets a usable cue even if prior sections ran long.
MIN_SLOT_WORD_CEILING = 40


def count_words(text: str) -> int:
    return len(text.split())


def estimate_duration_seconds(
    text: str,
    *,
    words_per_minute: int = DEFAULT_WORDS_PER_MINUTE,
) -> DurationEstimate:
    """Estimate narration duration from word count."""
    words = count_words(text)
    seconds = max(60, round(words / words_per_minute * 60))
    return DurationEstimate(seconds=seconds, method="word_count_heuristic")


def clamp_slot_word_ceiling(slot_ceiling: int, remaining_words: int) -> int:
    """Cap this section's word limit to what remains of the session speech budget."""
    remaining = max(0, int(remaining_words))
    ceiling = max(1, int(slot_ceiling))
    if remaining <= 0:
        return MIN_SLOT_WORD_CEILING
    return min(ceiling, max(MIN_SLOT_WORD_CEILING, remaining))


def format_composer_timing_brief(
    budget: SessionDurationBudget,
    *,
    slot: str,
    slot_word_ceiling: int,
    words_used_so_far: int = 0,
) -> str:
    """Authoritative session timing block for Agent 1 section prompts.

    Speech is sized to ``speech_share`` of wall-clock; intentional pause holds
    fill the rest downstream — the composer must not write a full session of words.
    """
    minutes = max(1, round(budget.target_duration_seconds / 60))
    speech_pct = int(round(budget.speech_share * 100))
    hold_pct = int(round(budget.hold_share * 100))
    used = max(0, int(words_used_so_far))
    remaining = max(0, budget.speech_budget_words - used)
    return "\n".join(
        [
            "## Session timing (authoritative — obey)",
            f"- Wall-clock target: {minutes} min = {budget.target_duration_seconds}s "
            "(what the listener experiences)",
            f"- Spoken budget ONLY: ~{budget.speech_budget_words} words ~ "
            f"{budget.speech_budget_seconds}s @ {budget.words_per_minute} WPM "
            f"({speech_pct}% of wall-clock)",
            f"- Silence / pause budget LATER: ~{budget.hold_budget_seconds}s "
            f"({hold_pct}%) — inserted after you write; you do NOT write "
            '"(pause)", "[pause]", or pad with words to fill time',
            "- Math: speech_seconds + hold_seconds ~ wall-clock",
            f"- This section (`{slot}`) hard ceiling: ≤ {slot_word_ceiling} words",
            f"- Words already used in prior sections: {used} / "
            f"{budget.speech_budget_words}; remaining for all later speech: {remaining}",
            "- Pause planner will place short holds (~5–10s) after nearly every beat; "
            "longer rests at section changes — write lean cues that leave room to rest",
            "- Do not write stage directions or pause markers; silence is planned downstream",
        ]
    )
