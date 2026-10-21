"""Consumer-ready ElevenLabs output formatters."""

from __future__ import annotations

from models.enums import EnhancementMode
from models.metadata import EnhancedScriptContent, NarrationChunk, SectionedScriptContent
from tts_enhancer.formats.api_chunked import apply_continuity_punctuation
from tts_enhancer.formats.plain_paste import format_plain_paste_text, format_voice_notes_text
from tts_enhancer.formats.v3_tagged import apply_v3_tags
from tts_enhancer.rewrite.chunking import build_chunks


def build_formatted_content(
    *,
    enhancement_mode: EnhancementMode,
    beats: list[str],
    sectioned_script: SectionedScriptContent | None,
    voice_direction_notes: list[str],
    pronunciation_notes: list[str],
    voice_model: str,
) -> EnhancedScriptContent:
    """Produce mode-specific content_json artifacts."""
    voice_notes_text = format_voice_notes_text(
        voice_direction_notes=voice_direction_notes,
        pronunciation_notes=pronunciation_notes,
    )
    extra: dict[str, object] = {
        "voice_model": voice_model,
        "enhancement_mode": enhancement_mode.value,
    }

    if enhancement_mode == EnhancementMode.PLAIN_PASTE:
        return EnhancedScriptContent(
            beats=beats,
            chunks=[],
            plain_paste_text=format_plain_paste_text(
                beats=beats,
                sectioned_script=sectioned_script,
            ),
            voice_notes_text=voice_notes_text,
            extra=extra,
        )

    raw_chunks = build_chunks(beats, mode=enhancement_mode)
    chunks = apply_continuity_punctuation(raw_chunks)

    if enhancement_mode == EnhancementMode.V3_TAGGED:
        chunks, tagging_applied = apply_v3_tags(chunks, voice_model=voice_model)
        extra["tagging_applied"] = tagging_applied

    return EnhancedScriptContent(
        beats=beats,
        chunks=chunks,
        voice_notes_text=voice_notes_text,
        extra=extra,
    )
