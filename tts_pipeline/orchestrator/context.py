"""Mutable workflow execution context passed between states."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from models.records import TranscriptAudioChunkRecord, TranscriptAudioJobRecord, TranscriptVersionRecord


@dataclass
class WorkflowContext:
    correlation_id: str
    audio_job_id: UUID | None = None
    tenant_id: UUID | None = None
    transcript_id: UUID | None = None
    transcript_version_id: UUID | None = None
    voice_profile_code: str | None = None
    job: TranscriptAudioJobRecord | None = None
    transcript_version: TranscriptVersionRecord | None = None
    chunks: list[TranscriptAudioChunkRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_error: str | None = None
