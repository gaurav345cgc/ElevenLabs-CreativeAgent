"""Persistence-aligned record models (Aurora rows)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from models.enums import AudioAssetKind, AudioJobStatus, AudioChunkStatus, EnhancementMode, TranscriptStatus, VersionKind


class TranscriptRecord(BaseModel):
    """Row shape for the transcript table."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    content_type: str
    status: TranscriptStatus
    created_at: datetime
    updated_at: datetime
    asset_id: UUID | None = None
    generation_code: str | None = None
    wound_id: str | None = None
    stage_no: int | None = None
    pillar_code: str | None = None
    current_version_id: UUID | None = None
    enhancement_attempt_count: int = 0
    last_error: str | None = None


class TranscriptVersionRecord(BaseModel):
    """Row shape for the transcript_version table."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transcript_id: UUID
    version_kind: VersionKind
    content_text: str
    created_by_agent: str
    metadata_json: dict[str, Any]
    created_at: datetime
    content_json: dict[str, Any] | None = None
    source_version_id: UUID | None = None
    enhancement_mode: EnhancementMode | None = None


class TranscriptJobEventRecord(BaseModel):
    """Row shape for the transcript_job_event audit table."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transcript_id: UUID
    event_type: str
    created_at: datetime
    event_payload: dict[str, Any] | None = None


class TranscriptAudioJobRecord(BaseModel):
    """Row shape for the transcript_audio_job table."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transcript_id: UUID
    transcript_version_id: UUID
    tenant_id: UUID
    idempotency_key: str
    voice_id: str
    model_id: str
    output_format: str
    status: AudioJobStatus
    created_at: datetime
    updated_at: datetime
    voice_profile_code: str | None = None
    total_chunks: int | None = None
    completed_chunks: int = 0
    failed_chunks: int = 0
    retry_count: int = 0
    enable_logging: bool = True
    apply_text_normalization: str = "auto"
    seed: int | None = None
    estimated_duration_ms: int | None = None
    final_asset_id: UUID | None = None
    failure_notes: str | None = None
    last_error: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    finished_at: datetime | None = None


class TranscriptAudioEventRecord(BaseModel):
    """Row shape for the transcript_audio_event audit table."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    audio_job_id: UUID
    event_type: str
    created_at: datetime
    event_payload: dict[str, Any] | None = None


class TranscriptAudioChunkRecord(BaseModel):
    """Row shape for the transcript_audio_chunk table."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    audio_job_id: UUID
    transcript_id: UUID
    transcript_version_id: UUID
    chunk_index: int
    status: AudioChunkStatus
    source_text: str
    output_format: str
    mime_type: str
    character_count: int
    created_at: datetime
    updated_at: datetime
    previous_text: str | None = None
    next_text: str | None = None
    previous_request_ids: list[str] | None = None
    next_request_ids: list[str] | None = None
    eleven_request_id: str | None = None
    output_object_key: str | None = None
    estimated_duration_ms: int | None = None
    actual_duration_ms: int | None = None
    response_headers_json: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    retry_count: int = 0


class TranscriptAudioAssetRecord(BaseModel):
    """Row shape for the transcript_audio_asset table."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    audio_job_id: UUID
    asset_kind: AudioAssetKind
    object_key: str
    mime_type: str
    created_at: datetime
    checksum: str | None = None
    byte_size: int | None = None
    metadata_json: dict[str, Any] | None = None
