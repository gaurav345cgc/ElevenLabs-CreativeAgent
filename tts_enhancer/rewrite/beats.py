"""Beat grouping for speakable narration."""

from __future__ import annotations

from tts_enhancer.rewrite.cleanup import split_sentences

DEFAULT_BEAT_MAX_WORDS = 22


def build_beats(text: str, *, max_words: int = DEFAULT_BEAT_MAX_WORDS) -> list[str]:
    """Group sentences into short beats suitable for ElevenLabs paste or chunking."""
    sentences = split_sentences(text)
    beats: list[str] = []
    current: list[str] = []
    current_words = 0

    for sentence in sentences:
        words = len(sentence.split())
        if current and current_words + words > max_words:
            beats.append(" ".join(current))
            current = [sentence]
            current_words = words
        else:
            current.append(sentence)
            current_words += words

    if current:
        beats.append(" ".join(current))
    return beats
