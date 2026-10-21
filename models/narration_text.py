"""Sentence and paragraph helpers shared by enhancement and TTS chunk planning."""

from __future__ import annotations

import re

from transcript_composer.duration import count_words

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")

# Trailing words that should not end a TTS chunk (incomplete thought).
WEAK_TRAILING_CONNECTORS = frozenset(
    {
        "and",
        "but",
        "because",
        "or",
        "so",
        "yet",
        "nor",
        "while",
        "when",
        "as",
        "if",
        "on",
        "upon",
        "into",
        "with",
        "for",
        "to",
        "at",
        "from",
        "about",
        "through",
        "during",
        "before",
        "after",
        "your",
        "their",
        "our",
        "my",
        "the",
    }
)


def normalize_paragraph_flow(text: str) -> str:
    """Turn soft line wraps into spaces so sentences are not split at newlines."""
    return re.sub(r"(?<=\S)\n(?=\S)", " ", text.strip())


def split_paragraphs(text: str) -> list[str]:
    return [
        normalize_paragraph_flow(part)
        for part in _PARAGRAPH_SPLIT.split(text.strip())
        if part.strip()
    ]


def split_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation only (never on bare line breaks)."""
    paragraphs = split_paragraphs(text) if _PARAGRAPH_SPLIT.search(text.strip()) else [normalize_paragraph_flow(text)]
    sentences: list[str] = []
    for paragraph in paragraphs:
        if not paragraph:
            continue
        parts = _SENTENCE_SPLIT.split(paragraph)
        sentences.extend(part.strip() for part in parts if part.strip())
    return sentences


def ends_complete_sentence(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped:
        return True
    return stripped[-1] in ".!?…\"')"


def ends_with_weak_connector(text: str) -> bool:
    words = text.strip().rstrip(".!?…").split()
    if not words:
        return False
    return words[-1].lower() in WEAK_TRAILING_CONNECTORS


def group_sentences_into_chunks(
    sentences: list[str],
    *,
    max_words: int,
    max_sentences: int = 4,
) -> list[str]:
    """Group whole sentences only — never split mid-sentence."""
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for sentence in sentences:
        words = count_words(sentence)
        if current and (
            current_words + words > max_words or len(current) >= max_sentences
        ):
            chunks.append(" ".join(current))
            current = [sentence]
            current_words = words
        else:
            current.append(sentence)
            current_words += words

    if current:
        chunks.append(" ".join(current))
    return chunks
