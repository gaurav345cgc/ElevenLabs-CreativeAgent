"""Sparse ElevenLabs v3 audio tag insertion."""

from __future__ import annotations

import re

from models.metadata import NarrationChunk

MAX_TAGS_PER_CHUNK = 2
TAG_PATTERN = re.compile(r"\[[^\]]+\]")

_TAG_INSERTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(take a breath|let your breath)\b", re.IGNORECASE), "[gentle pause]"),
    (re.compile(r"\b(soften|ease|gently)\b", re.IGNORECASE), "[softly]"),
    (re.compile(r"\b(welcome|warm|kindness)\b", re.IGNORECASE), "[warmly]"),
)


def apply_v3_tags(
    chunks: list[NarrationChunk],
    *,
    voice_model: str,
) -> tuple[list[NarrationChunk], bool]:
    """Apply sparse inline tags; fall back to untagged chunks when density is too high."""
    tagged = [_tag_chunk(chunk) for chunk in chunks]
    if not _tagging_quality_ok(chunks, tagged):
        return chunks, False
    return tagged, True


def _tag_chunk(chunk: NarrationChunk) -> NarrationChunk:
    text = chunk.text
    tags_used = 0
    for pattern, tag in _TAG_INSERTIONS:
        if tags_used >= MAX_TAGS_PER_CHUNK:
            break
        if tag in text:
            continue
        match = pattern.search(text)
        if not match:
            continue
        start = match.start()
        text = f"{text[:start]}{tag} {text[start:]}"
        tags_used += 1
    return chunk.model_copy(update={"text": text})


def _tagging_quality_ok(original: list[NarrationChunk], tagged: list[NarrationChunk]) -> bool:
    for chunk in tagged:
        if len(TAG_PATTERN.findall(chunk.text)) > MAX_TAGS_PER_CHUNK:
            return False
        if re.search(r"(?:\[[^\]]+\]\s*){3,}", chunk.text):
            return False
    return True
