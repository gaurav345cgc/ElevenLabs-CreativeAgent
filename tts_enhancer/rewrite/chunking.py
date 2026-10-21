"""Chunk long narration with continuity context for ElevenLabs API."""

from __future__ import annotations

from models.enums import EnhancementMode
from models.metadata import NarrationChunk
from models.narration_text import group_sentences_into_chunks, split_sentences
from transcript_composer.duration import count_words, estimate_duration_seconds

DEFAULT_CHUNK_MAX_WORDS = 75
CONTINUITY_CHARS = 180


def build_chunks(
    beats: list[str],
    *,
    mode: EnhancementMode,
    max_words: int = DEFAULT_CHUNK_MAX_WORDS,
) -> list[NarrationChunk]:
    if mode not in {EnhancementMode.API_CHUNKED, EnhancementMode.V3_TAGGED}:
        return []

    sentences: list[str] = []
    for beat in beats:
        sentences.extend(split_sentences(beat))

    grouped = group_sentences_into_chunks(sentences, max_words=max_words, max_sentences=4)
    chunks: list[NarrationChunk] = []
    for index, text in enumerate(grouped):
        previous_text = _continuity_excerpt(grouped[index - 1]) if index > 0 else None
        next_text = _continuity_excerpt(grouped[index + 1]) if index + 1 < len(grouped) else None
        duration = estimate_duration_seconds(text)
        chunks.append(
            NarrationChunk(
                sequence=index,
                text=text,
                previous_text=previous_text,
                next_text=next_text,
                estimated_duration_seconds=duration.seconds,
            )
        )
    return chunks


def _continuity_excerpt(text: str) -> str:
    excerpt = text.strip()
    if len(excerpt) <= CONTINUITY_CHARS:
        return excerpt
    return excerpt[-CONTINUITY_CHARS:]
