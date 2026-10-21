"""SQS and async handoff message contracts."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from models.common import SCHEMA_VERSION, build_enhancement_idempotency_key
from models.enums import EnhancementMode


class EnhancementJobMessage(BaseModel):
    """Identifier-only handoff from Agent 1 to Agent 2 via SQS."""

    schema_version: str = SCHEMA_VERSION
    transcript_id: UUID
    tenant_id: UUID
    raw_version_id: UUID
    requested_output_mode: EnhancementMode = EnhancementMode.PLAIN_PASTE
    voice_model: str = Field(default="eleven_multilingual_v2", max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=256)
    correlation_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def ensure_idempotency_key(self) -> EnhancementJobMessage:
        expected = build_enhancement_idempotency_key(self.transcript_id, self.raw_version_id)
        if self.idempotency_key != expected:
            msg = (
                "idempotency_key must match "
                f"'{{transcript_id}}:{{raw_version_id}}:enhancement-v1' (expected {expected!r})"
            )
            raise ValueError(msg)
        return self

    @classmethod
    def from_ids(
        cls,
        *,
        transcript_id: UUID,
        tenant_id: UUID,
        raw_version_id: UUID,
        requested_output_mode: EnhancementMode = EnhancementMode.PLAIN_PASTE,
        voice_model: str = "eleven_multilingual_v2",
        correlation_id: str | None = None,
    ) -> EnhancementJobMessage:
        return cls(
            transcript_id=transcript_id,
            tenant_id=tenant_id,
            raw_version_id=raw_version_id,
            requested_output_mode=requested_output_mode,
            voice_model=voice_model,
            idempotency_key=build_enhancement_idempotency_key(transcript_id, raw_version_id),
            correlation_id=correlation_id,
        )


def build_tts_workflow_idempotency_key(audio_job_id: UUID, *, strategy: str = "workflow-v1") -> str:
    """Stable idempotency key for TTS workflow SQS handoff."""
    return f"{audio_job_id}:{strategy}"


class TtsAudioJobMessage(BaseModel):
    """Identifier-only handoff from intake API to TTS worker Lambda via SQS."""

    schema_version: str = SCHEMA_VERSION
    audio_job_id: UUID
    tenant_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=256)
    correlation_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def ensure_idempotency_key(self) -> TtsAudioJobMessage:
        expected = build_tts_workflow_idempotency_key(self.audio_job_id)
        if self.idempotency_key != expected:
            msg = (
                "idempotency_key must match "
                f"'{{audio_job_id}}:workflow-v1' (expected {expected!r})"
            )
            raise ValueError(msg)
        return self

    @classmethod
    def from_audio_job_id(
        cls,
        *,
        audio_job_id: UUID,
        tenant_id: UUID,
        correlation_id: str | None = None,
    ) -> TtsAudioJobMessage:
        return cls(
            audio_job_id=audio_job_id,
            tenant_id=tenant_id,
            idempotency_key=build_tts_workflow_idempotency_key(audio_job_id),
            correlation_id=correlation_id,
        )
