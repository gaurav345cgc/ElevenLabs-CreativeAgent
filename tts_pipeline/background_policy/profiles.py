"""Approved background bed profiles — curated meditation ambience."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from tts_pipeline.background_policy.library_catalog import LIBRARY_BED_UPLOADS
from tts_pipeline.background_policy.schema import BackgroundProfile
from tts_pipeline.persistence.s3_keys import background_track_key

DEFAULT_BACKGROUND_PROFILE_CODE = "calm_ambient_01"
_LISTEN_NOTES_PATH = Path(__file__).resolve().parents[1] / "data" / "background_bed_listen_notes.json"

# Shared mix defaults for under-voice beds (speech-forward).
_DEFAULT_GAIN_DB = -30.0
_DEFAULT_FADE_IN_MS = 3000
_DEFAULT_FADE_OUT_MS = 5000
_DEFAULT_TAIL_PADDING_MS = 4000

_DISPLAY_NAMES: dict[str, str] = {
    "calm_ambient_01": "Calm ambient — primary bed",
    "bilateral_tranquility": "Bilateral tranquility",
    "bilateral_stillness": "Bilateral stillness",
    "bilateral_eternal": "Bilateral eternal",
    "transient": "Transient",
    "blessing": "Blessing (432 Hz)",
    "blossom": "Blossom (432 Hz)",
    "earth": "Earth (432 Hz)",
    "floating": "Floating (432 Hz)",
    "replenish": "Replenish (432 Hz)",
    "sanctuary": "Sanctuary (432 Hz)",
    "the_deep": "The Deep (432 Hz)",
    "timing": "Timing (432 Hz)",
    "tuning": "Tuning (432 Hz)",
    "ambient_light": "Ambient light",
    "calmness": "Calmness",
    "deeper_meaning": "Deeper meaning",
    "evolving_pads": "Evolving pads",
    "forgotten_place": "Forgotten place",
    "frozen_in_time": "Frozen in time",
    "forever": "Forever",
    "just_relax": "Just relax",
    "light_and_balanced": "Light and balanced",
    "peaceful_sleep": "Peaceful sleep",
    "pure_ambient": "Pure ambient",
    "reflections": "Reflections",
    "tranquil_reflections": "Tranquil reflections",
    "winter": "Winter",
}

# Mood tags for OpenAI matching (beds stay under the voice — never bright or FX-heavy).
PROFILE_MOODS: dict[str, str] = {
    "calm_ambient_01": "Warm generic pad; safe default for most guided practices.",
    "bilateral_tranquility": "Spacious, gently oscillating; settling and arrival.",
    "bilateral_stillness": "Sparse and still; quieting, body scans, pauses.",
    "bilateral_eternal": "Long, timeless, spacious; identity and grief work.",
    "transient": "Soft movement / in-between states; transitions and change.",
    "blessing": "Warm 432 Hz; gratitude, close, kindness.",
    "blossom": "Lighter opening energy; hope, beginning, growth.",
    "earth": "Grounded and rooted; body, work, embodiment.",
    "floating": "Airy and unhurried; lightness, letting go.",
    "replenish": "Restorative; fatigue, burnout, refill.",
    "sanctuary": "Safety and containment; rest, refuge, anxious settling.",
    "the_deep": "Darker, deeper; heavy wounds, grief, depth.",
    "timing": "Even, measured; work, focus, pacing.",
    "tuning": "Attunement and orienting; arriving into practice.",
    "ambient_light": "Soft daylight pad; gentle clarity without brightness.",
    "calmness": "Neutral calm pad; everyday daily practice.",
    "deeper_meaning": "Reflective, slightly introspective; purpose and meaning.",
    "evolving_pads": "Slow evolving wash; long sits, spacious holds.",
    "forgotten_place": "Quiet, slightly nostalgic; memory, absence.",
    "frozen_in_time": "Still, suspended; pause, freeze, waiting.",
    "forever": "Sustained long bed; continuity, endurance.",
    "just_relax": "Straightforward relax pad; micro / short practices.",
    "light_and_balanced": "Even and light; balance without lift or sparkle.",
    "peaceful_sleep": "Very quiet, sleep-adjacent; evening, deep rest.",
    "pure_ambient": "Minimal drone-like pad; least distracting under voice.",
    "reflections": "Gentle reflective; review, insight, closing.",
    "tranquil_reflections": "Soft reflective calm; integration at the end.",
    "winter": "Cool, sparse, still; solitude without heaviness.",
}


def display_name_for_code(code: str) -> str:
    return _DISPLAY_NAMES.get(code, code.replace("_", " ").title())


def mood_for_code(code: str) -> str:
    return PROFILE_MOODS.get(code, "Meditation-safe looping under-voice bed.")


@lru_cache(maxsize=1)
def _listen_notes_by_code() -> dict[str, dict]:
    if not _LISTEN_NOTES_PATH.exists():
        return {}
    try:
        payload = json.loads(_LISTEN_NOTES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    beds = payload.get("beds") if isinstance(payload, dict) else None
    if not isinstance(beds, dict):
        return {}
    return {str(code): note for code, note in beds.items() if isinstance(note, dict)}


def listen_notes_for_code(code: str) -> dict | None:
    return _listen_notes_by_code().get(code)


def listen_summary_for_code(code: str) -> str:
    """Concrete sonic line for the OpenAI selector (falls back to short mood tag)."""
    notes = listen_notes_for_code(code)
    if not notes:
        return mood_for_code(code)
    # Prefer v2 concrete_summary (objective metrics + strict listen).
    concrete = str(notes.get("concrete_summary") or "").strip()
    if concrete:
        return concrete
    one = str(notes.get("one_line") or "").strip()
    distinctive = str(notes.get("distinctive") or "").strip()
    best = str(notes.get("best_for") or "").strip()
    avoid = str(notes.get("avoid_when") or "").strip()
    listen = notes.get("listen") if isinstance(notes.get("listen"), dict) else {}
    parts = [one or mood_for_code(code)]
    detail = []
    if distinctive:
        detail.append(f"fingerprint={distinctive}")
    if best:
        detail.append(f"best_for={best}")
    if avoid:
        detail.append(f"avoid_when={avoid}")
    if listen.get("brightness"):
        detail.append(f"brightness={listen['brightness']}")
    if listen.get("low_end"):
        detail.append(f"low_end={listen['low_end']}")
    if detail:
        parts.append("(" + "; ".join(detail) + ")")
    return " ".join(parts)


def catalog_entries() -> list[dict[str, str]]:
    """Approved beds with labels for prompts and Script Hub."""
    return [
        {
            "code": code,
            "display_name": display_name_for_code(code),
            "mood": mood_for_code(code),
            "listen_summary": listen_summary_for_code(code),
            "track_object_key": background_track_key(code),
        }
        for code in sorted(set(LIBRARY_BED_UPLOADS.values()))
    ]


def _profile(code: str) -> BackgroundProfile:
    label = _DISPLAY_NAMES.get(code, code.replace("_", " ").title())
    return BackgroundProfile(
        code=code,
        display_name=label,
        description=f"Meditation-safe looping bed ({label}). Soft under-voice mix.",
        track_object_key=background_track_key(code),
        gain_db=_DEFAULT_GAIN_DB,
        fade_in_ms=_DEFAULT_FADE_IN_MS,
        fade_out_ms=_DEFAULT_FADE_OUT_MS,
        tail_padding_ms=_DEFAULT_TAIL_PADDING_MS,
        duck=False,
    )


APPROVED_BACKGROUND_PROFILES: dict[str, BackgroundProfile] = {
    code: _profile(code) for code in sorted(set(LIBRARY_BED_UPLOADS.values()))
}

# Guarantee default exists even if catalog map drifts.
if DEFAULT_BACKGROUND_PROFILE_CODE not in APPROVED_BACKGROUND_PROFILES:
    APPROVED_BACKGROUND_PROFILES[DEFAULT_BACKGROUND_PROFILE_CODE] = _profile(
        DEFAULT_BACKGROUND_PROFILE_CODE
    )
