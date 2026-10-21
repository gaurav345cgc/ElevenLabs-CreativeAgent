"""Human-in-the-loop pause markers for Script Hub review text.

Reviewers insert standalone lines like ``[pause 8s]`` between spoken units.
On approve we strip markers into spoken ``content_text`` / beats and persist a
``PausePlan`` under version metadata key ``human_pause_plan`` for the TTS plane.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from tts_pipeline.pause_planner.policy import (
    MIN_HOLD_SECONDS,
    PAUSE_POLICY_VERSION,
)
from tts_pipeline.pause_planner.schema import (
    PauseHold,
    PauseHoldKind,
    PausePlan,
    PausePlannerProvider,
)

HUMAN_PAUSE_PLAN_KEY = "human_pause_plan"
DRAFT_PAUSE_PLAN_KEY = "draft_pause_plan"
HUMAN_PROMPT_VERSION = "human-markers-v1"
HUMAN_MODEL_ID = "human-reviewer"
DEFAULT_HUMAN_PAUSE_SECONDS = MIN_HOLD_SECONDS  # 2 — after every spoken sentence



_PAUSE_LINE_RE = re.compile(
    r"^\s*\[pause(?:\s+(\d+)\s*s?)?\]\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ParsedPauseMarkedText:
    """Spoken units + holds parsed from Script Hub review text."""

    speech_units: list[str]
    holds: list[PauseHold]
    spoken_text: str


class HumanPauseMarkerError(ValueError):
    """Review text pause markers could not be parsed."""


def is_pause_marker_line(line: str) -> bool:
    return bool(_PAUSE_LINE_RE.match(line))


def parse_pause_marked_text(
    text: str,
    *,
    default_hold_seconds: int = DEFAULT_HUMAN_PAUSE_SECONDS,
    prefer_beats: bool = True,
) -> ParsedPauseMarkedText:
    """Split review text into speech units and ``[pause Ns]`` holds.

    Spoken units are blank-line-separated blocks. A pause marker must be its own
    block (typically a lone ``[pause 8s]`` line). Hold anchors use
    ``after_beat_index`` when ``prefer_beats`` is true, else ``after_paragraph_index``.
    """
    if default_hold_seconds < MIN_HOLD_SECONDS:
        raise HumanPauseMarkerError(
            f"default_hold_seconds must be >= {MIN_HOLD_SECONDS}"
        )

    units: list[str] = []
    holds: list[PauseHold] = []
    hold_seq = 0

    for block in _split_blank_line_blocks(text or ""):
        match = _PAUSE_LINE_RE.match(block)
        if match is not None and "\n" not in block:
            if not units:
                raise HumanPauseMarkerError(
                    "pause marker cannot appear before the first spoken line"
                )
            seconds_raw = match.group(1)
            hold_seconds = int(seconds_raw) if seconds_raw else int(default_hold_seconds)
            if hold_seconds < 1:
                raise HumanPauseMarkerError("pause seconds must be >= 1")

            after_index = len(units) - 1
            hold_seq += 1
            hold_kwargs: dict[str, Any] = {
                "hold_id": f"human_{hold_seq}_{after_index}",
                "hold_seconds": hold_seconds,
                "kind": PauseHoldKind.PRACTICE,
                "reason": "Human Script Hub pause marker.",
            }
            if prefer_beats:
                hold_kwargs["after_beat_index"] = after_index
            else:
                hold_kwargs["after_paragraph_index"] = after_index
            holds.append(PauseHold(**hold_kwargs))
            continue

        # Marker mixed into a speech block — not allowed (keeps parsing unambiguous).
        if any(is_pause_marker_line(line) for line in block.splitlines()):
            raise HumanPauseMarkerError(
                "pause markers must be alone on their own line, separated by a blank line"
            )
        units.append(block)

    if not units:
        raise HumanPauseMarkerError("approved text has no spoken content")

    spoken_text = "\n\n".join(units)
    return ParsedPauseMarkedText(
        speech_units=units,
        holds=holds,
        spoken_text=spoken_text,
    )


def _split_blank_line_blocks(text: str) -> list[str]:
    """Split on one-or-more blank lines; trim each block."""
    chunks = re.split(r"\n\s*\n+", text.strip()) if text.strip() else []
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def build_human_pause_plan(
    parsed: ParsedPauseMarkedText,
    *,
    target_duration_seconds: int | None = None,
    estimated_speech_seconds: int | None = None,
) -> PausePlan:
    """Build a ``PausePlan`` from parsed Script Hub markers."""
    return PausePlan(
        planner=PausePlannerProvider.HUMAN,
        model=HUMAN_MODEL_ID,
        prompt_version=HUMAN_PROMPT_VERSION,
        policy_version=PAUSE_POLICY_VERSION,
        target_duration_seconds=target_duration_seconds,
        estimated_speech_seconds=estimated_speech_seconds,
        holds=list(parsed.holds),
    )


def format_pause_marked_text(
    speech_units: list[str],
    holds: list[PauseHold] | None = None,
    *,
    prefer_beats: bool = True,
) -> str:
    """Render spoken units with ``[pause Ns]`` lines after units that have holds."""
    cleaned = [unit.strip() for unit in speech_units if unit and unit.strip()]
    if not cleaned:
        return ""

    holds_by_index: dict[int, list[int]] = {}
    for hold in holds or []:
        index = hold.after_beat_index if prefer_beats else hold.after_paragraph_index
        if index is None:
            continue
        holds_by_index.setdefault(index, []).append(int(hold.hold_seconds))

    parts: list[str] = []
    for index, unit in enumerate(cleaned):
        parts.append(unit)
        for seconds in holds_by_index.get(index, []):
            parts.append(f"[pause {seconds}s]")
    return "\n\n".join(parts)


def build_pause_review_text(
    *,
    content_text: str | None,
    content_json: dict[str, Any] | None,
    metadata_json: dict[str, Any] | None = None,
) -> str:
    """Script Hub editor text: beats/paragraphs with human or draft OpenAI pauses."""
    from tts_pipeline.pause_planner.draft import resolve_preview_pause_plan

    units = _speech_units_from_version(content_text, content_json)
    prefer_beats = bool(_beats_from_content_json(content_json))
    preview = resolve_preview_pause_plan(metadata_json)
    holds = list(preview.holds) if preview is not None else []
    return format_pause_marked_text(units, holds, prefer_beats=prefer_beats)


def load_human_pause_plan(metadata_json: dict[str, Any] | None) -> PausePlan | None:
    if not isinstance(metadata_json, dict):
        return None
    raw = metadata_json.get(HUMAN_PAUSE_PLAN_KEY)
    if raw is None:
        return None
    if isinstance(raw, PausePlan):
        return raw
    if not isinstance(raw, dict):
        raise HumanPauseMarkerError("human_pause_plan metadata must be an object")
    return PausePlan.model_validate(raw)


def _beats_from_content_json(content_json: dict[str, Any] | None) -> list[str]:
    if not isinstance(content_json, dict):
        return []
    raw = content_json.get("beats")
    if not isinstance(raw, list):
        return []
    return [item.strip() for item in raw if isinstance(item, str) and item.strip()]


def _speech_units_from_version(
    content_text: str | None,
    content_json: dict[str, Any] | None,
) -> list[str]:
    from tts_pipeline.pause_planner.anchors import expand_speech_units_to_sentences

    beats = _beats_from_content_json(content_json)
    if beats:
        return expand_speech_units_to_sentences(beats)
    text = (content_text or "").strip()
    if not text:
        return []
    units: list[str] = []
    for block in _split_blank_line_blocks(text):
        if is_pause_marker_line(block) and "\n" not in block:
            continue
        units.append(block)
    return expand_speech_units_to_sentences(units or [text])

