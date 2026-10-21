"""Resolve approved voice profiles into provider-ready synthesis requests."""

from __future__ import annotations

from tts_pipeline.generator.elevenlabs_client import (
    PronunciationDictionaryLocator,
    SpeechSynthesisRequest,
    VoiceSettings,
)
from tts_pipeline.voice_policy.profiles import APPROVED_VOICE_PROFILES, DEFAULT_VOICE_PROFILE_CODE
from tts_pipeline.voice_policy.schema import SeedPolicy, VoiceProfile, VoiceSettingsBounds


class VoicePolicyError(ValueError):
    """Raised when a caller requests disallowed voice configuration."""


def list_voice_profile_codes() -> list[str]:
    return sorted(APPROVED_VOICE_PROFILES)


def get_voice_profile(code: str) -> VoiceProfile:
    profile = APPROVED_VOICE_PROFILES.get(code)
    if profile is None:
        known = ", ".join(list_voice_profile_codes()) or "(none)"
        raise VoicePolicyError(f"Unknown voice profile {code!r}. Approved profiles: {known}")
    return profile


def resolve_seed(profile: VoiceProfile, *, requested_seed: int | None = None) -> int | None:
    if requested_seed is not None:
        if profile.seed_policy is SeedPolicy.PROHIBITED:
            raise VoicePolicyError(
                f"Profile {profile.code!r} does not allow seeds; omit requested_seed."
            )
        return requested_seed

    if profile.seed_policy is SeedPolicy.FIXED:
        if profile.default_seed is None:
            raise VoicePolicyError(f"Profile {profile.code!r} requires default_seed for FIXED policy.")
        return profile.default_seed

    if profile.seed_policy is SeedPolicy.OPTIONAL:
        return profile.default_seed

    return None


def resolve_enable_logging(profile: VoiceProfile, *, requested: bool | None = None) -> bool:
    value = profile.default_enable_logging if requested is None else requested
    if value is False and not profile.allow_logging_disabled:
        raise VoicePolicyError(
            f"Profile {profile.code!r} requires enable_logging=true for continuity and audit."
        )
    return value


def validate_voice_settings(settings: VoiceSettings, bounds: VoiceSettingsBounds) -> None:
    checks = (
        ("stability", settings.stability, bounds.stability_min, bounds.stability_max),
        ("similarity_boost", settings.similarity_boost, bounds.similarity_boost_min, bounds.similarity_boost_max),
        ("style", settings.style, bounds.style_min, bounds.style_max),
        ("speed", settings.speed, bounds.speed_min, bounds.speed_max),
    )
    for name, value, minimum, maximum in checks:
        if value is None:
            continue
        if value < minimum or value > maximum:
            raise VoicePolicyError(
                f"voice_settings.{name}={value} is outside allowed range [{minimum}, {maximum}]."
            )


def validate_pronunciation_dictionaries(
    profile: VoiceProfile,
    locators: list[PronunciationDictionaryLocator] | None,
) -> None:
    if not locators:
        return
    policy = profile.pronunciation_dictionary_policy
    if not policy.allowed:
        raise VoicePolicyError(
            f"Profile {profile.code!r} does not allow pronunciation dictionaries."
        )
    for locator in locators:
        if locator.pronunciation_dictionary_id not in policy.approved_dictionary_ids:
            raise VoicePolicyError(
                f"Pronunciation dictionary {locator.pronunciation_dictionary_id!r} "
                f"is not approved for profile {profile.code!r}."
            )


def assert_expressive_mode_allowed(profile: VoiceProfile, *, model_id: str) -> None:
    if model_id.startswith("eleven_v3") and not profile.expressive_mode_allowed:
        raise VoicePolicyError(
            f"Profile {profile.code!r} does not allow expressive v3 models (requested {model_id!r})."
        )


def build_speech_synthesis_request(
    profile_code: str,
    text: str,
    *,
    previous_text: str | None = None,
    next_text: str | None = None,
    previous_request_ids: list[str] | None = None,
    next_request_ids: list[str] | None = None,
    requested_seed: int | None = None,
    enable_logging: bool | None = None,
    voice_settings_override: VoiceSettings | None = None,
    pronunciation_dictionary_locators: list[PronunciationDictionaryLocator] | None = None,
) -> SpeechSynthesisRequest:
    """Build a provider request from an approved profile — not raw voice_id."""
    profile = get_voice_profile(profile_code)
    assert_expressive_mode_allowed(profile, model_id=profile.default_model_id)

    voice_settings = profile.default_voice_settings
    if voice_settings_override is not None:
        validate_voice_settings(voice_settings_override, profile.voice_settings_bounds)
        voice_settings = voice_settings_override

    validate_pronunciation_dictionaries(profile, pronunciation_dictionary_locators)

    return SpeechSynthesisRequest(
        text=text,
        voice_id=profile.voice_id,
        model_id=profile.default_model_id,
        output_format=profile.default_output_format,
        voice_settings=voice_settings,
        seed=resolve_seed(profile, requested_seed=requested_seed),
        apply_text_normalization=profile.default_apply_text_normalization,
        enable_logging=resolve_enable_logging(profile, requested=enable_logging),
        pronunciation_dictionary_locators=pronunciation_dictionary_locators,
        previous_text=previous_text,
        next_text=next_text,
        previous_request_ids=previous_request_ids,
        next_request_ids=next_request_ids,
    )


def build_default_speech_synthesis_request(text: str, **kwargs) -> SpeechSynthesisRequest:
    """Convenience wrapper using the default meditation profile."""
    return build_speech_synthesis_request(DEFAULT_VOICE_PROFILE_CODE, text, **kwargs)
