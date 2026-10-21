"""Agent output contracts (in-memory / pre-persist)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from models.enums import TranscriptStatus
from models.metadata import (
    DurationEstimate,
    EnhancedScriptContent,
    RawPatternMetadata,
    SectionedScriptContent,
    SelectedPatternPlan,
    TaxonomyContext,
)


class Agent1Output(BaseModel):
    """Result of Pattern Transcript Composer before/at persistence."""

    transcript_id: UUID
    version_id: UUID
    title: str = Field(min_length=1, max_length=512)
    transcript_text: str = Field(min_length=1)
    sectioned_script: SectionedScriptContent
    pattern_plan: SelectedPatternPlan
    taxonomy: TaxonomyContext
    duration_estimate: DurationEstimate
    metadata: RawPatternMetadata
    status: TranscriptStatus = TranscriptStatus.PENDING_ENHANCEMENT
    created_by_agent: str = "pattern_transcript_composer"


class Agent2Output(BaseModel):
    """Result of ElevenLabs Script Doctor before/at persistence."""

    transcript_id: UUID
    version_id: UUID
    source_version_id: UUID
    enhanced_full_script: str = Field(min_length=1)
    sectioned_script: SectionedScriptContent | None = None
    enhanced_content: EnhancedScriptContent
    voice_direction_notes: list[str] = Field(default_factory=list)
    pronunciation_notes: list[str] = Field(default_factory=list)
    duration_estimate: DurationEstimate | None = None
    created_by_agent: str = "elevenlabs_script_doctor"
