"""Phase 5 — voice policy tests."""

from __future__ import annotations

import pytest

from tts_pipeline.generator.config import (
    DEFAULT_APPLY_TEXT_NORMALIZATION,
    DEFAULT_ENABLE_LOGGING,
    DEFAULT_MODEL_ID,
    DEFAULT_OUTPUT_FORMAT,
)
from tts_pipeline.generator.elevenlabs_client import (
    PronunciationDictionaryLocator,
    VoiceSettings,
)
from tts_pipeline.voice_policy import (
    APPROVED_VOICE_PROFILES,
    DEFAULT_VOICE_PROFILE_CODE,
    VoicePolicyError,
    build_speech_synthesis_request,
    get_voice_profile,
    list_voice_profile_codes,
    resolve_enable_logging,
    resolve_seed,
    validate_pronunciation_dictionaries,
    validate_voice_settings,
)
from tts_pipeline.voice_policy.schema import MEDITATION_VOICE_SETTINGS_BOUNDS, SeedPolicy


def test_approved_profiles_include_architecture_default() -> None:
    assert DEFAULT_VOICE_PROFILE_CODE == "drew_primary"
    assert DEFAULT_VOICE_PROFILE_CODE in APPROVED_VOICE_PROFILES
    profile = get_voice_profile(DEFAULT_VOICE_PROFILE_CODE)
    assert profile.voice_id == "wgHvco1wiREKN0BdyVx5"
    assert profile.default_model_id == DEFAULT_MODEL_ID
    assert profile.default_output_format == DEFAULT_OUTPUT_FORMAT


def test_list_voice_profile_codes_is_sorted() -> None:
    codes = list_voice_profile_codes()
    assert codes == sorted(codes)
    assert codes == ["drew_primary"]


def test_build_request_uses_profile_defaults_not_raw_voice_id() -> None:
    request = build_speech_synthesis_request(
        "drew_primary",
        "Welcome to this guided meditation.",
    )
    profile = get_voice_profile("drew_primary")
    assert request.voice_id == profile.voice_id
    assert request.model_id == DEFAULT_MODEL_ID
    assert request.output_format == DEFAULT_OUTPUT_FORMAT
    assert request.apply_text_normalization == DEFAULT_APPLY_TEXT_NORMALIZATION
    assert request.enable_logging is DEFAULT_ENABLE_LOGGING
    assert request.seed == profile.default_seed
    assert request.voice_settings == profile.default_voice_settings


def test_build_request_supports_continuity_fields() -> None:
    request = build_speech_synthesis_request(
        "drew_primary",
        "Settle in.",
        previous_text="Welcome.",
        next_text="Notice your breath.",
        previous_request_ids=["req-a"],
        next_request_ids=["req-b"],
    )
    assert request.previous_text == "Welcome."
    assert request.next_text == "Notice your breath."
    assert request.previous_request_ids == ["req-a"]
    assert request.next_request_ids == ["req-b"]


def test_unknown_profile_raises() -> None:
    with pytest.raises(VoicePolicyError, match="Unknown voice profile"):
        build_speech_synthesis_request("not_a_profile", "Hello.")


def test_voice_settings_bounds_reject_out_of_range() -> None:
    with pytest.raises(VoicePolicyError, match="voice_settings.style"):
        validate_voice_settings(
            VoiceSettings(style=0.9),
            MEDITATION_VOICE_SETTINGS_BOUNDS,
        )


def test_voice_settings_override_within_bounds() -> None:
    override = VoiceSettings(stability=0.70, similarity_boost=0.80, style=0.10)
    request = build_speech_synthesis_request(
        "drew_primary",
        "Relax.",
        voice_settings_override=override,
    )
    assert request.voice_settings == override


def test_seed_policy_optional_uses_profile_default() -> None:
    profile = get_voice_profile("drew_primary")
    assert profile.seed_policy is SeedPolicy.OPTIONAL
    assert resolve_seed(profile) == profile.default_seed


def test_seed_policy_prohibited_rejects_requested_seed() -> None:
    profile = get_voice_profile("drew_primary").model_copy(
        update={"seed_policy": SeedPolicy.PROHIBITED}
    )
    with pytest.raises(VoicePolicyError, match="does not allow seeds"):
        resolve_seed(profile, requested_seed=42)


def test_enable_logging_cannot_be_disabled_for_profiles() -> None:
    profile = get_voice_profile("drew_primary")
    assert profile.allow_logging_disabled is False
    with pytest.raises(VoicePolicyError, match="enable_logging=true"):
        resolve_enable_logging(profile, requested=False)


def test_pronunciation_dictionary_not_allowed_by_default() -> None:
    profile = get_voice_profile("drew_primary")
    locators = [
        PronunciationDictionaryLocator(
            pronunciation_dictionary_id="dict-1",
            version_id="v1",
        )
    ]
    with pytest.raises(VoicePolicyError, match="does not allow pronunciation dictionaries"):
        validate_pronunciation_dictionaries(profile, locators)


def test_expressive_v3_not_allowed() -> None:
    profile = get_voice_profile("drew_primary")
    assert profile.expressive_mode_allowed is False
    assert profile.default_model_id == "eleven_multilingual_v2"


def test_all_profiles_use_premade_safe_defaults() -> None:
    for code in list_voice_profile_codes():
        profile = get_voice_profile(code)
        assert profile.expressive_mode_allowed is False
        assert profile.allow_logging_disabled is False
        assert profile.default_model_id == "eleven_multilingual_v2"
        assert profile.default_output_format == "mp3_44100_128"
        assert profile.voice_id
        assert code in profile.code
