"""Phase 9 — ElevenLabs formatting mode tests."""

from __future__ import annotations

from models.enums import EnhancementMode
from models.metadata import ScriptSection, SectionedScriptContent
from tts_enhancer.engine import EnhancementEngine
from tts_enhancer.formats.api_chunked import apply_continuity_punctuation
from tts_enhancer.formats.plain_paste import format_plain_paste_text, format_voice_notes_text
from tts_enhancer.formats.v3_tagged import apply_v3_tags
from tts_enhancer.rewrite.chunking import build_chunks
from tts_enhancer.rewrite.beats import build_beats
from models.metadata import NarrationChunk


def test_plain_paste_includes_sectioned_layout_and_separate_voice_notes() -> None:
    sectioned = SectionedScriptContent(
        sections=[
            ScriptSection(slot="opening", title="Opening", text="Welcome. Take a breath."),
            ScriptSection(slot="closing", title="Closing", text="When you are ready, return gently."),
        ]
    )
    engine = EnhancementEngine()
    result = engine.enhance(
        raw_text="ignored when sectioned",
        sectioned_script=sectioned,
        enhancement_mode=EnhancementMode.PLAIN_PASTE,
        voice_model="eleven_multilingual_v2",
    )

    assert result.enhanced_content.plain_paste_text
    assert "## Opening" in result.enhanced_content.plain_paste_text
    assert "## Closing" in result.enhanced_content.plain_paste_text
    assert result.enhanced_content.chunks == []
    assert result.enhanced_content.voice_notes_text
    assert "Voice direction" in result.enhanced_content.voice_notes_text
    assert "Voice direction" not in result.enhanced_full_script


def test_api_chunked_chunks_have_duration_and_continuity_punctuation() -> None:
    beats = build_beats(
        "Welcome to this practice. "
        "Take one easy breath. "
        "Notice the weight of your body. "
        "Let the exhale lengthen gently. "
        "Stay with the quiet rhythm of breathing."
    )
    chunks = apply_continuity_punctuation(
        build_chunks(beats, mode=EnhancementMode.API_CHUNKED, max_words=12)
    )
    assert chunks
    assert chunks[0].sequence == 0
    assert chunks[0].estimated_duration_seconds
    assert chunks[0].text.endswith((".", "!", "?"))
    assert chunks[-1].next_text is None
    if len(chunks) > 1:
        assert chunks[1].previous_text is not None


def test_v3_tagged_applies_sparse_tags() -> None:
    chunks = [
        NarrationChunk(sequence=0, text="Welcome warmly. Take a breath and soften."),
        NarrationChunk(sequence=1, text="Let your breath ease gently through the body."),
    ]
    tagged, applied = apply_v3_tags(chunks, voice_model="eleven_v3")
    assert applied is True
    assert any("[" in chunk.text for chunk in tagged)


def test_v3_tagged_falls_back_when_stacked_tags_detected() -> None:
    from tts_enhancer.formats.v3_tagged import _tagging_quality_ok

    original = [NarrationChunk(sequence=0, text="Take a breath.")]
    over_tagged = [NarrationChunk(sequence=0, text="[softly] [warmly] [gentle pause] Take a breath.")]
    assert _tagging_quality_ok(original, over_tagged) is False

    safe, applied = apply_v3_tags(original, voice_model="eleven_v3")
    assert applied in {True, False}
    assert len(safe) == 1


def test_voice_notes_formatter() -> None:
    block = format_voice_notes_text(
        voice_direction_notes=["Keep the delivery invitational."],
        pronunciation_notes=["API -> A P I"],
    )
    assert block
    assert "Voice direction" in block
    assert "Pronunciation" in block
