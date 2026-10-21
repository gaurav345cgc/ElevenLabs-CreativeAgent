"""API chunk formatting with continuity-safe edges."""

from __future__ import annotations

import re

from models.metadata import NarrationChunk

TRAILING_HANGING_PUNCT = re.compile(r"[,;:\-–—]\s*$")
INCOMPLETE_ENDING = re.compile(r"[^.!?…\"')\]]\s*$")


def apply_continuity_punctuation(chunks: list[NarrationChunk]) -> list[NarrationChunk]:
    """Ensure chunk boundaries end cleanly for ElevenLabs continuity stitching."""
    if not chunks:
        return []

    normalized_texts = [_normalize_chunk_edge(text) for text in (chunk.text for chunk in chunks)]
    updated: list[NarrationChunk] = []

    for index, chunk in enumerate(chunks):
        text = normalized_texts[index]
        previous_text = _continuity_excerpt(normalized_texts[index - 1]) if index > 0 else None
        next_text = _continuity_excerpt(normalized_texts[index + 1]) if index + 1 < len(normalized_texts) else None
        updated.append(
            chunk.model_copy(
                update={
                    "text": text,
                    "previous_text": previous_text,
                    "next_text": next_text,
                }
            )
        )
    return updated


def _normalize_chunk_edge(text: str) -> str:
    cleaned = text.strip()
    cleaned = TRAILING_HANGING_PUNCT.sub("", cleaned)
    if INCOMPLETE_ENDING.search(cleaned):
        cleaned = f"{cleaned}."
    return cleaned


def _continuity_excerpt(text: str, *, max_chars: int = 180) -> str:
    excerpt = _normalize_chunk_edge(text)
    if len(excerpt) <= max_chars:
        return excerpt
    return excerpt[-max_chars:]
