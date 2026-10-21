"""Structural cleanup for TTS narration."""

from __future__ import annotations

import re

from models.narration_text import split_sentences

FILLER_PATTERN = re.compile(
    r"\b(?:um+|uh+|erm|hmm|ah+)\b[,.]?\s*",
    re.IGNORECASE,
)
MULTISPACE = re.compile(r"[ \t]{2,}")
ARTIFACT_PATTERN = re.compile(r"\[(?:pause|silence|music)\]", re.IGNORECASE)
ELLIPSES = re.compile(r"\.{3,}")


def remove_fillers(text: str) -> str:
    return FILLER_PATTERN.sub("", text)


def remove_artifacts(text: str) -> str:
    return ARTIFACT_PATTERN.sub("", text)


def collapse_whitespace(text: str) -> str:
    text = MULTISPACE.sub(" ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def remove_duplicate_starts(text: str) -> str:
    """Drop consecutive paragraphs that begin with the same opening phrase."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(paragraphs) < 2:
        return text.strip()

    deduped: list[str] = [paragraphs[0]]
    for paragraph in paragraphs[1:]:
        previous = deduped[-1]
        prev_opening = _opening_phrase(previous)
        current_opening = _opening_phrase(paragraph)
        if prev_opening and prev_opening == current_opening:
            continue
        deduped.append(paragraph)
    return "\n\n".join(deduped)


def complete_sentence_fragments(text: str) -> str:
    sentences = split_sentences(text)
    completed: list[str] = []
    for sentence in sentences:
        cleaned = sentence.strip()
        if not cleaned:
            continue
        if cleaned[-1] not in ".!?":
            cleaned = f"{cleaned}."
        completed.append(cleaned)
    return " ".join(completed)


def cleanup_text(text: str) -> str:
    cleaned = remove_fillers(text)
    cleaned = remove_artifacts(cleaned)
    cleaned = remove_duplicate_starts(cleaned)
    cleaned = complete_sentence_fragments(cleaned)
    cleaned = ELLIPSES.sub(".", cleaned)
    return collapse_whitespace(cleaned)


def polish_rewritten_text(text: str) -> str:
    """Post-process Script Doctor output while preserving paragraph breaks."""
    from models.narration_text import normalize_paragraph_flow

    cleaned = remove_fillers(text)
    cleaned = remove_artifacts(cleaned)
    cleaned = remove_duplicate_starts(cleaned)

    paragraphs: list[str] = []
    for paragraph in re.split(r"\n\s*\n", cleaned.strip()):
        normalized = normalize_paragraph_flow(paragraph)
        if not normalized:
            continue
        if normalized[-1] not in ".!?…":
            normalized = f"{normalized}."
        paragraphs.append(normalized)

    if not paragraphs:
        return cleanup_text(text)

    cleaned = "\n\n".join(paragraphs)
    cleaned = ELLIPSES.sub("…", cleaned)
    return collapse_whitespace(cleaned)


def _opening_phrase(paragraph: str) -> str:
    words = paragraph.split()
    if len(words) < 3:
        return ""
    return " ".join(words[:3]).lower()
