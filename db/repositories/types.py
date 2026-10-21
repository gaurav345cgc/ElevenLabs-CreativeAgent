"""Input types for repository writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from models.enums import AudioChunkStatus, AudioJobStatus, AudioAssetKind, EnhancementMode, TranscriptStatus, VersionKind


@dataclass(frozen=True, slots=True)
class CreateTranscriptInput:
    tenant_id: UUID
    content_type: str
    status: TranscriptStatus = TranscriptStatus.CREATED
    asset_id: UUID | None = None
    generation_code: str | None = None
    wound_id: str | None = None
    stage_no: int | None = None
    pillar_code: str | None = None
    transcript_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class InsertTranscriptVersionInput:
    transcript_id: UUID
    version_kind: VersionKind
    content_text: str
    created_by_agent: str
    metadata_json: dict[str, Any]
    version_id: UUID | None = None
    content_json: dict[str, Any] | None = None
    source_version_id: UUID | None = None
    enhancement_mode: EnhancementMode | None = None


@dataclass(frozen=True, slots=True)
class TranscriptWithVersions:
    transcript: Any  # TranscriptRecord — avoid circular import at runtime use TranscriptRecord
    versions: list[Any] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CreateAudioJobInput:
    transcript_id: UUID
    transcript_version_id: UUID
    tenant_id: UUID
    idempotency_key: str
    voice_profile_code: str
    voice_id: str
    model_id: str
    output_format: str
    enable_logging: bool
    apply_text_normalization: str
    metadata_json: dict[str, Any]
    seed: int | None = None
    status: AudioJobStatus = AudioJobStatus.CREATED
    audio_job_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CreateAudioChunkInput:
    audio_job_id: UUID
    transcript_id: UUID
    transcript_version_id: UUID
    chunk_index: int
    source_text: str
    output_format: str
    mime_type: str
    character_count: int
    previous_text: str | None = None
    next_text: str | None = None
    estimated_duration_ms: int | None = None
    metadata_json: dict[str, Any] | None = None
    status: AudioChunkStatus = AudioChunkStatus.PLANNED
    chunk_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CreateAudioAssetInput:
    audio_job_id: UUID
    asset_kind: AudioAssetKind
    object_key: str
    mime_type: str
    checksum: str | None = None
    byte_size: int | None = None
    metadata_json: dict[str, Any] | None = None
    asset_id: UUID | None = None
