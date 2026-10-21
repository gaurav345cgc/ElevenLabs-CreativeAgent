"""ElevenLabs Script Doctor — guide-driven rewrite pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from models.enums import EnhancementMode
from models.metadata import EnhancedScriptContent, SectionedScriptContent
from transcript_composer.duration import estimate_duration_seconds
from tts_enhancer.formats import build_formatted_content
from tts_enhancer.rewrite import build_beats, build_voice_direction_notes
from tts_enhancer.quality import validate_enhanced_output
from tts_enhancer.script_doctor import ScriptDoctor, get_default_script_doctor


@dataclass(frozen=True, slots=True)
class EnhancementEngineResult:
    enhanced_full_script: str
    sectioned_script: SectionedScriptContent | None
    enhanced_content: EnhancedScriptContent
    voice_direction_notes: list[str]
    pronunciation_notes: list[str]
    duration_estimate_seconds: int


class EnhancementEngine:
    """Apply Agent2-guide Script Doctor rewrite, beats, and chunking."""

    def __init__(self, *, script_doctor: ScriptDoctor | None = None) -> None:
        self._script_doctor = script_doctor or get_default_script_doctor()

    def enhance(
        self,
        *,
        raw_text: str,
        sectioned_script: SectionedScriptContent | None,
        enhancement_mode: EnhancementMode,
        voice_model: str,
    ) -> EnhancementEngineResult:
        enhanced_full_script, sectioned_output, pronunciation_notes = self._script_doctor.rewrite(
            raw_text=raw_text,
            sectioned_script=sectioned_script,
            voice_model=voice_model,
        )

        validate_enhanced_output(raw_text=raw_text, enhanced_text=enhanced_full_script)

        beats = build_beats(enhanced_full_script)
        voice_notes = build_voice_direction_notes(enhanced_full_script)
        pronunciation_notes = _dedupe_notes(pronunciation_notes)
        enhanced_content = build_formatted_content(
            enhancement_mode=enhancement_mode,
            beats=beats,
            sectioned_script=sectioned_output,
            voice_direction_notes=voice_notes,
            pronunciation_notes=pronunciation_notes,
            voice_model=voice_model,
        )
        duration = estimate_duration_seconds(enhanced_full_script)

        return EnhancementEngineResult(
            enhanced_full_script=enhanced_full_script,
            sectioned_script=sectioned_output,
            enhanced_content=enhanced_content,
            voice_direction_notes=voice_notes,
            pronunciation_notes=pronunciation_notes,
            duration_estimate_seconds=duration.seconds,
        )


def get_default_enhancement_engine() -> EnhancementEngine:
    return EnhancementEngine()


def _dedupe_notes(notes: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for note in notes:
        if note not in seen:
            seen.add(note)
            unique.append(note)
    return unique
