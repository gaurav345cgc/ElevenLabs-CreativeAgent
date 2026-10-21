"""Shared session timing budget: speech + holds ≈ target wall-clock.

Agent 1 sizes narration to the speech share; the OpenAI pause planner / Script Hub
fills the hold share so advertised length (e.g. 10 min) includes intentional silence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

# Meditative narration pace — slightly slower than conversational speech.
DEFAULT_WORDS_PER_MINUTE = 130

# Leave room for practice/section/integration holds inside the advertised length.
# Leaner speech share: fewer words under voice; more intentional silence.
# Example: 10 min target → ~6.2 min speech + ~3.8 min holds.
DEFAULT_SPEECH_SHARE = 0.62
DEFAULT_HOLD_SHARE = 1.0 - DEFAULT_SPEECH_SHARE

# Product QA band around wall-clock (speech + holds + short bed tail).
DURATION_TOLERANCE_RATIO = 0.10


@dataclass(frozen=True, slots=True)
class SessionDurationBudget:
    """Coordinated speech/hold budgets for one meditation job."""

    target_duration_seconds: int
    speech_budget_seconds: int
    hold_budget_seconds: int
    speech_budget_words: int
    speech_share: float
    hold_share: float
    words_per_minute: int

    def as_metadata(self) -> dict:
        """Flat dict suitable for transcript / job metadata_json."""
        return {
            "target_duration_seconds": self.target_duration_seconds,
            "target_duration_minutes": max(1, round(self.target_duration_seconds / 60)),
            "speech_budget_seconds": self.speech_budget_seconds,
            "hold_budget_seconds": self.hold_budget_seconds,
            "speech_budget_words": self.speech_budget_words,
            "speech_share": self.speech_share,
            "hold_share": self.hold_share,
            "words_per_minute": self.words_per_minute,
            "duration_budget_version": "duration-budget-v2",
        }


def build_session_duration_budget(
    target_duration_minutes: int,
    *,
    speech_share: float = DEFAULT_SPEECH_SHARE,
    words_per_minute: int = DEFAULT_WORDS_PER_MINUTE,
) -> SessionDurationBudget:
    if target_duration_minutes < 1:
        raise ValueError("target_duration_minutes must be >= 1")
    if not 0.4 <= speech_share <= 0.9:
        raise ValueError("speech_share must be between 0.4 and 0.9")
    if words_per_minute < 60:
        raise ValueError("words_per_minute must be >= 60")

    target_seconds = int(target_duration_minutes) * 60
    speech_seconds = max(60, int(round(target_seconds * speech_share)))
    hold_seconds = max(0, target_seconds - speech_seconds)
    speech_words = max(80, int(round(speech_seconds / 60 * words_per_minute)))
    return SessionDurationBudget(
        target_duration_seconds=target_seconds,
        speech_budget_seconds=speech_seconds,
        hold_budget_seconds=hold_seconds,
        speech_budget_words=speech_words,
        speech_share=speech_share,
        hold_share=1.0 - speech_share,
        words_per_minute=words_per_minute,
    )


def budget_from_metadata(mapping: dict | None) -> SessionDurationBudget | None:
    """Rebuild a budget from stored metadata when fields are present."""
    if not isinstance(mapping, dict):
        return None
    minutes = mapping.get("target_duration_minutes")
    seconds = mapping.get("target_duration_seconds")
    if minutes is None and seconds is None:
        return None
    if minutes is None:
        minutes = max(1, int(round(int(seconds) / 60)))
    speech_share = mapping.get("speech_share")
    wpm = mapping.get("words_per_minute")
    kwargs: dict = {}
    if speech_share is not None:
        kwargs["speech_share"] = float(speech_share)
    if wpm is not None:
        kwargs["words_per_minute"] = int(wpm)
    return build_session_duration_budget(int(minutes), **kwargs)


def session_budget_dict(budget: SessionDurationBudget) -> dict:
    return asdict(budget)


# Keys copied RAW → ENHANCED → APPROVED_FINAL → audio job for pause budgeting.
DURATION_BUDGET_METADATA_KEYS: tuple[str, ...] = (
    "target_duration_seconds",
    "target_duration_minutes",
    "speech_budget_seconds",
    "hold_budget_seconds",
    "speech_budget_words",
    "speech_share",
    "hold_share",
    "words_per_minute",
    "duration_budget_version",
)


def copy_duration_budget_metadata(source: dict | None) -> dict:
    """Flatten duration-budget fields from a version/job metadata mapping."""
    if not isinstance(source, dict):
        return {}
    out: dict = {}
    for key in DURATION_BUDGET_METADATA_KEYS:
        value = source.get(key)
        if value is not None:
            out[key] = value
    return out
