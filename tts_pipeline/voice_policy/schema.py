"""Voice profile schema and policy bounds for ElevenLabs TTS."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from tts_pipeline.generator.config import (
    DEFAULT_APPLY_TEXT_NORMALIZATION,
    DEFAULT_ENABLE_LOGGING,
    DEFAULT_MODEL_ID,
    DEFAULT_OUTPUT_FORMAT,
)
from tts_pipeline.generator.elevenlabs_client import VoiceSettings


class SeedPolicy(StrEnum):
    """How a profile may use deterministic seeds."""

    FIXED = "fixed"
    OPTIONAL = "optional"
    PROHIBITED = "prohibited"


class VoiceSettingsBounds(BaseModel):
    """Allowed ranges for optional voice_settings overrides."""

    model_config = ConfigDict(frozen=True)

    stability_min: float = 0.0
    stability_max: float = 1.0
    similarity_boost_min: float = 0.0
    similarity_boost_max: float = 1.0
    style_min: float = 0.0
    style_max: float = 1.0
    speed_min: float = 0.7
    speed_max: float = 1.2


MEDITATION_VOICE_SETTINGS_BOUNDS = VoiceSettingsBounds(
    stability_min=0.45,
    stability_max=0.85,
    similarity_boost_min=0.60,
    similarity_boost_max=0.95,
    style_min=0.0,
    style_max=0.25,
    speed_min=0.70,
    speed_max=1.05,
)


class PronunciationDictionaryPolicy(BaseModel):
    """Which pronunciation dictionaries a profile may attach."""

    model_config = ConfigDict(frozen=True)

    allowed: bool = False
    approved_dictionary_ids: frozenset[str] = Field(default_factory=frozenset)


class VoiceProfile(BaseModel):
    """Approved narration profile mapped to ElevenLabs provider settings."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = ""
    voice_id: str = Field(min_length=1)
    default_model_id: str = DEFAULT_MODEL_ID
    default_output_format: str = DEFAULT_OUTPUT_FORMAT
    default_voice_settings: VoiceSettings
    default_apply_text_normalization: str = DEFAULT_APPLY_TEXT_NORMALIZATION
    default_enable_logging: bool = DEFAULT_ENABLE_LOGGING
    default_seed: int | None = None
    seed_policy: SeedPolicy = SeedPolicy.OPTIONAL
    voice_settings_bounds: VoiceSettingsBounds = MEDITATION_VOICE_SETTINGS_BOUNDS
    pronunciation_dictionary_policy: PronunciationDictionaryPolicy = Field(
        default_factory=PronunciationDictionaryPolicy
    )
    allow_logging_disabled: bool = False
    expressive_mode_allowed: bool = False
    approved_model_ids: frozenset[str] = Field(default_factory=lambda: frozenset({DEFAULT_MODEL_ID}))
    approved_output_formats: frozenset[str] = Field(
        default_factory=lambda: frozenset({DEFAULT_OUTPUT_FORMAT})
    )
