"""Approved voice profiles — ElevenLabs voices for guided meditation."""

from __future__ import annotations

from tts_pipeline.generator.config import DEFAULT_MODEL_ID, DEFAULT_OUTPUT_FORMAT
from tts_pipeline.generator.elevenlabs_client import VoiceSettings
from tts_pipeline.voice_policy.schema import (
    MEDITATION_VOICE_SETTINGS_BOUNDS,
    PronunciationDictionaryPolicy,
    SeedPolicy,
    VoiceProfile,
)

_DREW_VOICE_ID = "Nyip1VgoS6bg9Vl30y8v"

_MEDITATION_DEFAULTS = VoiceSettings(
    stability=0.65,
    similarity_boost=0.78,
    style=0.08,
    use_speaker_boost=False,
    speed=0.82,
)

_NO_PRONUNCIATION = PronunciationDictionaryPolicy(allowed=False)


def _meditation_profile(
    *,
    code: str,
    display_name: str,
    description: str,
    voice_id: str,
    default_seed: int = 1337,
) -> VoiceProfile:
    return VoiceProfile(
        code=code,
        display_name=display_name,
        description=description,
        voice_id=voice_id,
        default_model_id=DEFAULT_MODEL_ID,
        default_output_format=DEFAULT_OUTPUT_FORMAT,
        default_voice_settings=_MEDITATION_DEFAULTS,
        default_seed=default_seed,
        seed_policy=SeedPolicy.OPTIONAL,
        voice_settings_bounds=MEDITATION_VOICE_SETTINGS_BOUNDS,
        pronunciation_dictionary_policy=_NO_PRONUNCIATION,
        allow_logging_disabled=False,
        expressive_mode_allowed=False,
        approved_model_ids=frozenset({DEFAULT_MODEL_ID}),
        approved_output_formats=frozenset({DEFAULT_OUTPUT_FORMAT}),
    )


APPROVED_VOICE_PROFILES: dict[str, VoiceProfile] = {
    profile.code: profile
    for profile in (
        _meditation_profile(
            code="drew_primary",
            display_name="Drew — primary narration",
            description="Primary guided meditation voice (Drew).",
            voice_id=_DREW_VOICE_ID,
        ),
    )
}

DEFAULT_VOICE_PROFILE_CODE = "drew_primary"
