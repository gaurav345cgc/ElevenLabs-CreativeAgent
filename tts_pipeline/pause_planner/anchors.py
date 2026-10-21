"""Extract beat / paragraph anchors from an enhanced transcript version."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from models.records import TranscriptVersionRecord
from tts_pipeline.chunk_planner.sentences import split_paragraphs, split_sentences
from tts_pipeline.pause_planner.errors import PausePlannerValidationError

PreferredAnchor = Literal["beats", "paragraphs"]


@dataclass(frozen=True, slots=True)
class PauseAnchors:
    """Planner input anchors extracted from an enhanced transcript version."""

    beats: list[str]
    paragraphs: list[str]
    preferred: PreferredAnchor


def expand_speech_units_to_sentences(units: list[str]) -> list[str]:
    """Flatten multi-sentence beats/paragraphs so holds can land after each sentence."""
    expanded: list[str] = []
    for unit in units:
        cleaned = (unit or "").strip()
        if not cleaned:
            continue
        sentences = split_sentences(cleaned)
        if sentences:
            expanded.extend(sentences)
        else:
            expanded.append(cleaned)
    return expanded


def extract_pause_anchors(version: TranscriptVersionRecord) -> PauseAnchors:
    """Return deterministic pause anchors for the OpenAI planner.

    Preference order:
    1. Non-blank ``content_json.beats`` → preferred ``beats``
    2. Else paragraphs from ``content_text`` → preferred ``paragraphs``
    3. If both empty → ``PausePlannerValidationError``

    Multi-sentence units are expanded to one sentence per anchor so density and
    Script Hub markers can place a hold after every spoken sentence.
    """
    beats = expand_speech_units_to_sentences(_extract_beats(version.content_json))
    paragraphs = expand_speech_units_to_sentences(_extract_paragraphs(version.content_text))

    if beats:
        return PauseAnchors(beats=beats, paragraphs=paragraphs, preferred="beats")
    if paragraphs:
        return PauseAnchors(beats=[], paragraphs=paragraphs, preferred="paragraphs")
    raise PausePlannerValidationError(
        "enhanced version has no usable beats or paragraphs for pause planning"
    )


def _extract_beats(content_json: dict | None) -> list[str]:
    if not isinstance(content_json, dict):
        return []
    raw_beats = content_json.get("beats")
    if not isinstance(raw_beats, list):
        return []
    beats: list[str] = []
    for item in raw_beats:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if cleaned:
            beats.append(cleaned)
    return beats


def _extract_paragraphs(content_text: str | None) -> list[str]:
    text = (content_text or "").strip()
    if not text:
        return []
    return [paragraph.strip() for paragraph in split_paragraphs(text) if paragraph.strip()]
