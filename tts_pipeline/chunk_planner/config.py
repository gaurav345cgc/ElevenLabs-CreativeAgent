"""Chunk planning bounds and defaults."""

from __future__ import annotations

# ElevenLabs-friendly segment sizes for meditation narration.
# Keep chunks at one sentence so silence holds can land after every sentence
# (multi-sentence chunks merge holds onto a single stitch boundary).
MIN_CHUNK_CHARS = 8
MAX_CHUNK_CHARS = 2500
MAX_CHUNK_WORDS = 75
MAX_SENTENCES_PER_CHUNK = 1
CONTINUITY_CHARS = 180

MEDITATION_WORDS_PER_MINUTE = 110
