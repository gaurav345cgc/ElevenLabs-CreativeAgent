"""API response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from models.common import SCHEMA_VERSION
from models.enums import EnhancementMode, TranscriptStatus, VersionKind
from models.metadata import DurationEstimate, SelectedPatternPlan


class CreateTranscriptResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    transcript_id: UUID
    version_id: UUID
    title: str
    status: TranscriptStatus
    duration_estimate_seconds: int
    queue_message_id: str
    pattern_plan: SelectedPatternPlan
    correlation_id: str | None = None


class TranscriptStatusResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    transcript_id: UUID
    tenant_id: UUID
    status: TranscriptStatus
    title: str | None = None
    current_version_id: UUID | None = None
    enhancement_attempt_count: int
    last_error: str | None = None
    content_type: str
    generation_code: str | None = None
    wound_id: str | None = None
    stage_no: int | None = None
    pillar_code: str | None = None
    duration_estimate: DurationEstimate | None = None
    created_at: datetime
    updated_at: datetime
    # Populated when Approve & Send to TTS successfully creates/enqueues an audio job.
    audio_job_id: UUID | None = None
    tts_queue_message_id: str | None = None
    tts_enqueue_error: str | None = None


class TranscriptVersionItem(BaseModel):
    version_id: UUID
    version_kind: VersionKind
    created_at: datetime
    created_by_agent: str
    source_version_id: UUID | None = None
    enhancement_mode: EnhancementMode | None = None
    content_text: str | None = Field(
        default=None,
        description="Included only when include_content=true",
    )
    content_json: dict[str, Any] | None = Field(
        default=None,
        description="Included only when include_content=true (beats / structured package)",
    )
    pause_review_text: str | None = Field(
        default=None,
        description=(
            "Script Hub editor text with optional [pause Ns] markers between beats/"
            "paragraphs. Included when include_content=true."
        ),
    )
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class TranscriptVersionsResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    transcript_id: UUID
    versions: list[TranscriptVersionItem]


class TranscriptWaitResponse(TranscriptStatusResponse):
    """Status after blocking until enhancement completes or the wait window expires."""

    ready: bool = Field(
        description="True when status is ENHANCED (enhancement finished successfully).",
    )
    enhanced_content_text: str | None = Field(
        default=None,
        description="ELEVENLABS_ENHANCED narration when ready=true and include_content=true.",
    )
    raw_content_text: str | None = Field(
        default=None,
        description="RAW_PATTERN narration when include_content=true.",
    )


class RetryEnhancementResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    transcript_id: UUID
    raw_version_id: UUID
    status: TranscriptStatus
    queue_message_id: str
    requested_output_mode: EnhancementMode
    voice_model: str
    correlation_id: str | None = None


class AudioJobStatusResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    audio_job_id: UUID
    transcript_id: UUID
    transcript_version_id: UUID
    tenant_id: UUID
    status: str
    voice_id: str
    model_id: str
    output_format: str
    total_chunks: int | None = None
    completed_chunks: int = 0
    failed_chunks: int = 0
    last_error: str | None = None
    final_asset_id: UUID | None = None
    master_asset_id: UUID | None = None
    manifest_asset_id: UUID | None = None
    pause_hold_count: int | None = Field(
        default=None,
        description="Hold count from mapped/normalized pause plan metadata when present.",
    )
    pause_total_hold_seconds: int | None = Field(
        default=None,
        description="Total hold seconds from pause plan metadata when present.",
    )
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class AudioJobManifestResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    audio_job_id: UUID
    transcript_id: UUID
    tenant_id: UUID
    manifest_asset_id: UUID
    manifest_object_key: str
    final_asset_id: UUID | None = None
    final_object_key: str | None = None
    master_asset_id: UUID | None = None
    master_object_key: str | None = None
    manifest: dict[str, Any] = Field(description="Parsed audio_manifest.json payload")
    manifest_url: str | None = Field(
        default=None,
        description="Presigned HTTPS URL when include_urls=true",
    )
    final_url: str | None = Field(
        default=None,
        description="Presigned HTTPS URL for final.mp3 when include_urls=true",
    )
    master_url: str | None = Field(
        default=None,
        description=(
            "Presigned HTTPS URL for master.mp3 when include_urls=true. "
            "Primary download when present; final_url remains for debugging."
        ),
    )


class CreateAudioJobResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    audio_job_id: UUID
    transcript_id: UUID
    transcript_version_id: UUID
    tenant_id: UUID
    status: str
    voice_id: str
    model_id: str
    output_format: str
    created: bool
    queue_message_id: str | None = None
    correlation_id: str | None = None


class BackgroundProfileItem(BaseModel):
    code: str
    display_name: str
    mood: str
    track_object_key: str
    preview_url: str | None = None


class BackgroundProfilesResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    default_code: str
    profiles: list[BackgroundProfileItem]


class LibraryItem(BaseModel):
    """One listen-ready meditation in the catalog browser."""

    transcript_id: UUID
    audio_job_id: UUID
    title: str | None = None
    status: TranscriptStatus
    content_type: str
    generation_code: str | None = None
    generation_label: str | None = None
    wound_id: str | None = None
    wound_label: str | None = None
    stage_no: int | None = None
    pillar_code: str | None = None
    pillar_label: str | None = None
    pause_hold_count: int | None = None
    pause_total_hold_seconds: int | None = None
    duration_estimate: DurationEstimate | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class LibraryResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    tenant_id: UUID
    item_count: int
    items: list[LibraryItem]


class ClearPendingReviewResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    tenant_id: UUID
    dismissed_count: int
    transcript_ids: list[UUID]


class RetainLibraryResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    tenant_id: UUID
    kept_transcript_ids: list[UUID]
    archived_job_count: int
    remaining_item_count: int
