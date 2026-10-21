"""Approved voice profiles, models, output formats, and voice_settings bounds."""

from tts_pipeline.voice_policy.profiles import (
    APPROVED_VOICE_PROFILES,
    DEFAULT_VOICE_PROFILE_CODE,
)
from tts_pipeline.voice_policy.resolver import (
    VoicePolicyError,
    build_default_speech_synthesis_request,
    build_speech_synthesis_request,
    get_voice_profile,
    list_voice_profile_codes,
    resolve_enable_logging,
    resolve_seed,
    validate_pronunciation_dictionaries,
    validate_voice_settings,
)
from tts_pipeline.voice_policy.schema import (
    MEDITATION_VOICE_SETTINGS_BOUNDS,
    PronunciationDictionaryPolicy,
    SeedPolicy,
    VoiceProfile,
    VoiceSettingsBounds,
)

__all__ = [
    "APPROVED_VOICE_PROFILES",
    "DEFAULT_VOICE_PROFILE_CODE",
    "MEDITATION_VOICE_SETTINGS_BOUNDS",
    "PronunciationDictionaryPolicy",
    "SeedPolicy",
    "VoicePolicyError",
    "VoiceProfile",
    "VoiceSettingsBounds",
    "build_default_speech_synthesis_request",
    "build_speech_synthesis_request",
    "get_voice_profile",
    "list_voice_profile_codes",
    "resolve_enable_logging",
    "resolve_seed",
    "validate_pronunciation_dictionaries",
    "validate_voice_settings",
]
