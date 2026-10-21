"""Normalize taxonomy codes from the markdown corpus."""

from __future__ import annotations

import re

GENERATION_ALIASES: dict[str, str] = {
    "gen z": "gen_z",
    "millennial": "millennial",
    "gen x": "gen_x",
    "boomer": "boomer",
    "all": "all_generations",
}

FAMILY_COMPOSITION_SLOTS: dict[str, str] = {
    "opening_intro": "opening",
    "settling_grounding": "settling",
    "somatic_scan": "body",
    "breath_attention": "breath",
    "mind_reframing_kindness": "mind_heart",
    "mind_reframing_oneness": "mind_heart",
    "affirmation_release": "mind_heart",
    "closing_transition": "closing",
}

DEFAULT_PATTERN_BY_SLOT: dict[str, str] = {
    "opening": "guided_meditation_intro",
    "settling": "grounding_settling_posture",
    "body": "somatic_scan",
    "breath": "breath_attention",
    "mind_heart": "mind_reframing_oneness",
    "closing": "closing_transition",
}

WOUND_RANGE_PATTERN = re.compile(
    r"^(?P<prefix>[a-z]{2})[-_](?P<start>\d+)[–—-](?P<end>\d+)$",
    re.IGNORECASE,
)
WOUND_ID_PATTERN = re.compile(r"\(([A-Z]{2}-\d{2})\)")
PILLAR_PATTERN = re.compile(r"P(\d{2})")


def normalize_generation(raw: str) -> str | None:
    value = raw.strip().lower()
    if not value or value in {"—", "-"}:
        return None
    return GENERATION_ALIASES.get(value)


def normalize_wound_id(raw: str) -> str | None:
    value = raw.strip()
    if not value or value in {"—", "-"}:
        return None

    lowered = value.lower().replace("-", "_")
    range_match = WOUND_RANGE_PATTERN.match(lowered)
    if range_match:
        return None

    if lowered.startswith("any "):
        return None

    return lowered


def expand_wound_ids(raw: str) -> list[str]:
    value = raw.strip()
    if not value or value in {"—", "-"}:
        return []

    range_match = WOUND_RANGE_PATTERN.match(value.lower().replace("-", "_"))
    if range_match:
        prefix = range_match.group("prefix")
        start = int(range_match.group("start"))
        end = int(range_match.group("end"))
        return [f"{prefix}_{num:02d}" for num in range(start, end + 1)]

    normalized = normalize_wound_id(value)
    return [normalized] if normalized else []


def parse_stage_numbers(raw: str) -> list[int]:
    value = raw.strip().replace("–", "-").replace("—", "-")
    range_match = re.search(r"(\d+)\s*-\s*(\d+)", value)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        return list(range(start, end + 1))

    single_match = re.search(r"\d+", value)
    if single_match:
        return [int(single_match.group(0))]
    return []


def parse_pillar_codes(raw: str) -> list[str]:
    return [f"p{match.group(1).lower()}" for match in PILLAR_PATTERN.finditer(raw)]


def extract_wound_id_from_text(text: str) -> str | None:
    match = WOUND_ID_PATTERN.search(text)
    if not match:
        return None
    return normalize_wound_id(match.group(1))
