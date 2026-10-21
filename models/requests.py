"""API and intake request schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from models.enums import EnhancementMode
from models.validation import validate_taxonomy_combination


class CreateTranscriptRequest(BaseModel):
    """Intake payload for creating a transcript job (Agent 1)."""

    tenant_id: UUID
    content_type: str = Field(min_length=1, max_length=64)
    generation_code: str = Field(min_length=1, max_length=64)
    wound_id: str = Field(min_length=1, max_length=128)
    stage_no: int = Field(ge=1, le=99)
    target_duration_minutes: int = Field(ge=1, le=180)
    pillar_code: str | None = Field(default=None, max_length=64)
    principles: list[str] = Field(default_factory=list)
    title_hint: str | None = Field(default=None, max_length=512)
    asset_id: UUID | None = None
    requested_output_mode: EnhancementMode = EnhancementMode.PLAIN_PASTE
    voice_model: str = Field(default="eleven_multilingual_v2", max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)

    @field_validator("generation_code", "wound_id", "pillar_code", "content_type", mode="before")
    @classmethod
    def strip_optional_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("principles")
    @classmethod
    def normalize_principles(cls, values: list[str]) -> list[str]:
        return [p.strip() for p in values if p and p.strip()]

    @model_validator(mode="after")
    def validate_taxonomy(self) -> CreateTranscriptRequest:
        validate_taxonomy_combination(
            generation_code=self.generation_code,
            wound_id=self.wound_id,
            stage_no=self.stage_no,
            pillar_code=self.pillar_code,
            content_type=self.content_type,
        )
        return self


class RetryEnhancementRequest(BaseModel):
    """Optional body for re-queuing a failed or review-required transcript."""

    requested_output_mode: EnhancementMode | None = None
    voice_model: str | None = Field(default=None, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=128)


class CreateAudioJobApiRequest(BaseModel):
    """Intake payload for creating a TTS audio job and enqueueing workflow."""

    tenant_id: UUID
    transcript_id: UUID
    transcript_version_id: UUID
    voice_profile_code: str = Field(default="drew_primary", min_length=1, max_length=64)
    seed_override: int | None = Field(default=None, ge=0)
    correlation_id: str | None = Field(default=None, max_length=128)


class ApproveTranscriptRequest(BaseModel):
    """Payload for approving an enhanced transcript."""

    approved_text: str | None = Field(default=None)
    background_profile_code: str | None = Field(default=None, max_length=64)
    correlation_id: str | None = Field(default=None, max_length=128)


class SetBackgroundProfileRequest(BaseModel):
    """Reviewer override for the catalog bed used on mix."""

    profile_code: str = Field(min_length=1, max_length=64)


class RetainLibraryRequest(BaseModel):
    """Keep only these transcripts in the listen library; archive other completed jobs."""

    transcript_ids: list[UUID] = Field(min_length=1)
