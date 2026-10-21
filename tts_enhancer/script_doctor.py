"""Script Doctor rewriters — LLM (Agent2-guide) and deterministic fallback."""

from __future__ import annotations

from typing import Any, Protocol

from models.metadata import ScriptSection, SectionedScriptContent
from transcript_composer.llm_config import require_openai_api_key, resolve_openai_api_key, resolve_openai_model
from tts_enhancer.llm_config import resolve_script_doctor_mode
from tts_enhancer.prompts import build_system_prompt
from tts_enhancer.rewrite.cleanup import polish_rewritten_text
from tts_enhancer.rewrite.normalize import normalize_punctuation, normalize_tokens

_SLOT_GUIDE_HINTS: dict[str, str] = {
    "opening": "Opening (settling in) — welcome and intention.",
    "settling": "Body positioning — posture and comfort.",
    "body": "Main practice — somatic scan, one area per sentence.",
    "breath": "Breathing focus — breath awareness, low instruction density.",
    "mind_heart": "Main practice — mind/heart reframing with soft suggestion.",
    "closing": "Closing — integration and gentle return.",
}


class ScriptDoctor(Protocol):
    def rewrite(
        self,
        *,
        raw_text: str,
        sectioned_script: SectionedScriptContent | None,
        voice_model: str,
    ) -> tuple[str, SectionedScriptContent | None, list[str]]: ...


class DeterministicScriptDoctor:
    """Offline rewrite for tests and environments without an API key."""

    def rewrite(
        self,
        *,
        raw_text: str,
        sectioned_script: SectionedScriptContent | None,
        voice_model: str,
    ) -> tuple[str, SectionedScriptContent | None, list[str]]:
        pronunciation_notes: list[str] = []
        if sectioned_script is not None:
            enhanced_sections: list[ScriptSection] = []
            for section in sectioned_script.sections:
                text, notes = _polish_section(section.text)
                pronunciation_notes.extend(notes)
                enhanced_sections.append(
                    ScriptSection(slot=section.slot, title=section.title, text=text)
                )
            full_script = "\n\n".join(section.text for section in enhanced_sections)
            return full_script, SectionedScriptContent(sections=enhanced_sections), pronunciation_notes

        text, notes = _polish_section(raw_text)
        return text, None, notes


class OpenAIScriptDoctor:
    """Rewrite narration with OpenAI using guide/Agent2-guide.md as the system prompt."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._model = model or resolve_openai_model()
        self._client = client or self._build_client(api_key or require_openai_api_key())
        self._system_prompt = build_system_prompt()

    def rewrite(
        self,
        *,
        raw_text: str,
        sectioned_script: SectionedScriptContent | None,
        voice_model: str,
    ) -> tuple[str, SectionedScriptContent | None, list[str]]:
        pronunciation_notes: list[str] = []
        if sectioned_script is not None:
            enhanced_sections: list[ScriptSection] = []
            prior_excerpt = ""
            for section in sectioned_script.sections:
                rewritten = self._rewrite_section_text(
                    source_text=section.text,
                    slot=section.slot,
                    section_title=section.title,
                    prior_excerpt=prior_excerpt,
                    voice_model=voice_model,
                )
                text, notes = _polish_section(rewritten)
                pronunciation_notes.extend(notes)
                enhanced_sections.append(
                    ScriptSection(slot=section.slot, title=section.title, text=text)
                )
                prior_excerpt = text[-400:]
            full_script = "\n\n".join(section.text for section in enhanced_sections)
            return full_script, SectionedScriptContent(sections=enhanced_sections), pronunciation_notes

        rewritten = self._rewrite_section_text(
            source_text=raw_text,
            slot=None,
            section_title=None,
            prior_excerpt="",
            voice_model=voice_model,
        )
        text, notes = _polish_section(rewritten)
        return text, None, notes

    def _rewrite_section_text(
        self,
        *,
        source_text: str,
        slot: str | None,
        section_title: str | None,
        prior_excerpt: str,
        voice_model: str,
    ) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": _build_user_prompt(
                    source_text=source_text,
                    slot=slot,
                    section_title=section_title,
                    prior_excerpt=prior_excerpt,
                    voice_model=voice_model,
                )},
            ],
            temperature=0.3,
        )
        content = response.choices[0].message.content
        if not content or not content.strip():
            label = slot or "script"
            raise RuntimeError(f"OpenAI returned empty Script Doctor output for {label!r}")
        return content.strip()

    @staticmethod
    def _build_client(api_key: str) -> Any:
        from openai import OpenAI

        return OpenAI(api_key=api_key)


def get_default_script_doctor() -> ScriptDoctor:
    mode = resolve_script_doctor_mode()
    if mode == "deterministic":
        return DeterministicScriptDoctor()
    if mode == "openai":
        return OpenAIScriptDoctor()
    if resolve_openai_api_key():
        return OpenAIScriptDoctor()
    return DeterministicScriptDoctor()


def script_doctor_name(doctor: ScriptDoctor) -> str:
    if isinstance(doctor, OpenAIScriptDoctor):
        return "openai"
    if isinstance(doctor, DeterministicScriptDoctor):
        return "deterministic"
    return type(doctor).__name__


def _polish_section(text: str) -> tuple[str, list[str]]:
    cleaned = polish_rewritten_text(text)
    cleaned, notes = normalize_tokens(cleaned)
    cleaned = normalize_punctuation(cleaned)
    return cleaned, notes


def _build_user_prompt(
    *,
    source_text: str,
    slot: str | None,
    section_title: str | None,
    prior_excerpt: str,
    voice_model: str,
) -> str:
    continuity = (
        f"Prior section ending (match tone and rhythm; do not repeat):\n{prior_excerpt}\n"
        if prior_excerpt
        else "This is the first section of the script."
    )
    section_block = ""
    if slot:
        hint = _SLOT_GUIDE_HINTS.get(slot, "")
        title = section_title or slot.replace("_", " ").title()
        section_block = f"""
## Section context
- composition_slot: {slot}
- section_title: {title}
- template role: {hint or "(follow guide structure for this beat)"}
"""

    v3_note = ""
    if "v3" in voice_model.lower():
        v3_note = (
            "\nTarget voice model is ElevenLabs v3. You may use light v3 audio tags "
            "(e.g. [whispers], [softly]) sparingly — at most one or two per section."
        )

    return f"""Rewrite the following meditation narration into ElevenLabs-ready TTS text.
Apply every rule in your enhancement guide strictly.
Preserve meaning and therapeutic intent.
Remove near-duplicate / paraphrased restatements; do not add words.
Prefer leaner output when the source repeats the same cue.
{section_block}
## Voice model
{voice_model}{v3_note}

## Continuity
{continuity}

## Source narration (rewrite this)
{source_text.strip()}

Return rewritten narration text only — line breaks and blank lines as prosody cues."""
