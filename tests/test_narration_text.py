"""Tests for shared narration sentence helpers."""

from __future__ import annotations

from models.narration_text import (
    ends_complete_sentence,
    group_sentences_into_chunks,
    normalize_paragraph_flow,
    split_sentences,
)


def test_soft_line_wrap_is_not_a_sentence_break() -> None:
    text = "Take a deep breath and focus on\nthe atmosphere around you."
    sentences = split_sentences(text)
    assert len(sentences) == 1
    assert "focus on the atmosphere" in sentences[0]


def test_group_sentences_never_splits_mid_sentence() -> None:
    sentences = [
        "Take a deep breath and focus on the atmosphere around you.",
        "Let your shoulders soften.",
    ]
    chunks = group_sentences_into_chunks(sentences, max_words=8, max_sentences=1)
    assert len(chunks) == 2
    assert chunks[0].endswith("around you.")
    assert chunks[1].startswith("Let your")


def test_normalize_paragraph_flow() -> None:
    assert normalize_paragraph_flow("line one\nline two") == "line one line two"


def test_ends_complete_sentence() -> None:
    assert ends_complete_sentence("Breathe in.")
    assert not ends_complete_sentence("focus on")
