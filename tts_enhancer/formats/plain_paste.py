"""Plain-paste formatting for manual ElevenLabs UI input."""

from __future__ import annotations

from models.metadata import ScriptSection, SectionedScriptContent
from tts_enhancer.rewrite.beats import build_beats


def format_plain_paste_text(
    *,
    beats: list[str],
    sectioned_script: SectionedScriptContent | None,
) -> str:
    """Build sectioned, beat-grouped text for manual paste (narration only)."""
    if sectioned_script is not None:
        return _format_sectioned_plain_paste(sectioned_script.sections)
    return _format_beats_plain_paste(beats)


def format_voice_notes_text(
    *,
    voice_direction_notes: list[str],
    pronunciation_notes: list[str],
) -> str | None:
    """Voice notes block kept outside the main narrated script."""
    lines: list[str] = []
    if voice_direction_notes:
        lines.append("Voice direction")
        lines.extend(f"- {note}" for note in voice_direction_notes)
    if pronunciation_notes:
        if lines:
            lines.append("")
        lines.append("Pronunciation")
        lines.extend(f"- {note}" for note in pronunciation_notes)
    if not lines:
        return None
    return "\n".join(lines)


def _format_sectioned_plain_paste(sections: list[ScriptSection]) -> str:
    blocks: list[str] = []
    for section in sections:
        title = section.title or section.slot.replace("_", " ").title()
        beats = build_beats(section.text)
        body = "\n\n".join(beats) if beats else section.text.strip()
        blocks.append(f"## {title}\n\n{body}")
    return "\n\n".join(blocks)


def _format_beats_plain_paste(beats: list[str]) -> str:
    return "\n\n".join(beat.strip() for beat in beats if beat.strip())
