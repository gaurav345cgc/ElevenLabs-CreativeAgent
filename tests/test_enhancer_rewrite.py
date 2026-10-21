"""Unit tests for Agent 2 rewrite pipeline."""

from __future__ import annotations

from models.enums import EnhancementMode
from tts_enhancer.engine import EnhancementEngine
from tts_enhancer.rewrite import build_beats, build_chunks, cleanup_text, normalize_tokens
from tts_enhancer.rewrite.cleanup import remove_fillers, split_sentences


def test_remove_fillers() -> None:
    raw = "Um, take a breath and, uh, soften your shoulders."
    cleaned = remove_fillers(raw)
    assert "Um" not in cleaned
    assert "uh" not in cleaned
    assert "take a breath" in cleaned


def test_cleanup_completes_fragments() -> None:
    raw = "Welcome here\n\nLet the shoulders soften"
    cleaned = cleanup_text(raw)
    assert cleaned.endswith(".")


def test_normalize_numbers() -> None:
    text, notes = normalize_tokens("Rest for 3 breaths before continuing.")
    assert "three" in text
    assert notes


def test_build_beats_groups_sentences() -> None:
    text = "Welcome. Take a breath. Soften the jaw. Release the shoulders."
    beats = build_beats(text, max_words=8)
    assert len(beats) >= 2
    assert all(beat.endswith(".") for beat in beats)


def test_api_chunked_includes_continuity_fields() -> None:
    beats = build_beats(
        "Welcome to this practice. "
        "Take one easy breath. "
        "Notice the weight of your body. "
        "Let the exhale lengthen gently. "
        "Stay with the quiet rhythm of breathing."
    )
    chunks = build_chunks(beats, mode=EnhancementMode.API_CHUNKED, max_words=12)
    assert chunks
    assert chunks[0].previous_text is None
    assert chunks[0].next_text is not None
    if len(chunks) > 1:
        assert chunks[1].previous_text is not None


def test_plain_paste_has_beats_without_chunks() -> None:
    engine = EnhancementEngine()
    result = engine.enhance(
        raw_text="Um, welcome. Take 2 slow breaths.",
        sectioned_script=None,
        enhancement_mode=EnhancementMode.PLAIN_PASTE,
        voice_model="eleven_multilingual_v2",
    )
    assert result.enhanced_content.beats
    assert result.enhanced_content.chunks == []
    assert result.enhanced_content.plain_paste_text
    assert "two" in result.enhanced_full_script.lower()
    assert result.voice_direction_notes


def test_split_sentences_handles_multiple_sentences() -> None:
    sentences = split_sentences("One. Two! Three?")
    assert sentences == ["One.", "Two!", "Three?"]
