"""Metadata and content_json structures stored on transcript versions."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from models.enums import EnhancementMode


class TaxonomyContext(BaseModel):
    """Generation / wound / stage / pillar context from the content brief."""

    generation_code: str = Field(min_length=1, max_length=64)
    wound_id: str = Field(min_length=1, max_length=128)
    stage_no: int = Field(ge=1, le=99)
    pillar_code: str | None = Field(default=None, max_length=64)
    principles: list[str] = Field(default_factory=list)


class PatternSlotSelection(BaseModel):
    """One slot in the six-stage composition flow."""

    slot: str = Field(description="opening | settling | body | breath | mind_heart | closing")
    pattern_family: str = Field(min_length=1, max_length=128)


class SelectedPatternPlan(BaseModel):
    """Pattern families chosen for each composition stage."""

    slots: list[PatternSlotSelection] = Field(min_length=6, max_length=6)
    schema_version: str = "1.0"


class DurationEstimate(BaseModel):
    """Estimated narration duration in seconds."""

    seconds: int = Field(ge=0)
    method: str = Field(default="word_count_heuristic", max_length=64)


class VoiceModelTarget(BaseModel):
    """ElevenLabs voice model target for enhancement."""

    voice_model: str = Field(min_length=1, max_length=128)
    enhancement_mode: EnhancementMode = EnhancementMode.PLAIN_PASTE


class RawPatternMetadata(BaseModel):
    """metadata_json for RAW_PATTERN versions (Agent 1)."""

    schema_version: str = "1.0"
    taxonomy: TaxonomyContext
    pattern_plan: SelectedPatternPlan
    duration_estimate: DurationEstimate
    title: str = Field(min_length=1, max_length=512)
    example_reference_ids: list[str] = Field(default_factory=list)
    script_generator: str | None = Field(
        default=None,
        description="openai | template — which generator produced the script",
    )
    validation_report: dict | None = Field(
        default=None,
        description="Agent 1 post-compose validation summary (pattern index + examples checks)",
    )
    validation_engine: str | None = Field(
        default=None,
        description="openai | rules — which validator produced the report",
    )
    # Coordinated with pause planner: speech sized so holds can fill the rest.
    target_duration_seconds: int | None = Field(default=None, ge=0)
    target_duration_minutes: int | None = Field(default=None, ge=1)
    speech_budget_seconds: int | None = Field(default=None, ge=0)
    hold_budget_seconds: int | None = Field(default=None, ge=0)
    speech_budget_words: int | None = Field(default=None, ge=0)
    speech_share: float | None = Field(default=None, ge=0.0, le=1.0)
    hold_share: float | None = Field(default=None, ge=0.0, le=1.0)
    words_per_minute: int | None = Field(default=None, ge=60)
    duration_budget_version: str | None = Field(default=None, max_length=64)


class EnhancedVersionMetadata(BaseModel):
    """metadata_json for ELEVENLABS_ENHANCED versions (Agent 2)."""

    schema_version: str = "1.0"
    source_version_id: UUID
    voice_model: str
    enhancement_mode: EnhancementMode
    duration_estimate: DurationEstimate | None = None
    voice_direction_notes: list[str] = Field(default_factory=list)
    pronunciation_notes: list[str] = Field(default_factory=list)
    # Copied from RAW so Script Hub / pause planner keep wall-clock coordination.
    target_duration_seconds: int | None = Field(default=None, ge=0)
    target_duration_minutes: int | None = Field(default=None, ge=1)
    speech_budget_seconds: int | None = Field(default=None, ge=0)
    hold_budget_seconds: int | None = Field(default=None, ge=0)
    speech_budget_words: int | None = Field(default=None, ge=0)
    speech_share: float | None = Field(default=None, ge=0.0, le=1.0)
    hold_share: float | None = Field(default=None, ge=0.0, le=1.0)
    words_per_minute: int | None = Field(default=None, ge=60)
    duration_budget_version: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=512)


class ScriptSection(BaseModel):
    """One section in a sectioned script."""

    slot: str
    title: str | None = None
    text: str = Field(min_length=1)


class SectionedScriptContent(BaseModel):
    """content_json shape for RAW_PATTERN sectioned output."""

    schema_version: str = "1.0"
    sections: list[ScriptSection] = Field(min_length=1)


class NarrationChunk(BaseModel):
    """One synthesis chunk for api_chunked / v3_tagged modes."""

    sequence: int = Field(ge=0)
    text: str = Field(min_length=1)
    previous_text: str | None = None
    next_text: str | None = None
    estimated_duration_seconds: int | None = Field(default=None, ge=0)


class EnhancedScriptContent(BaseModel):
    """content_json shape for ELEVENLABS_ENHANCED output."""

    schema_version: str = "1.0"
    beats: list[str] = Field(default_factory=list)
    chunks: list[NarrationChunk] = Field(default_factory=list)
    plain_paste_text: str | None = Field(
        default=None,
        description="Manual ElevenLabs UI paste layout (beats/sections only, no voice notes)",
    )
    voice_notes_text: str | None = Field(
        default=None,
        description="Voice direction + pronunciation notes kept outside narrated text",
    )
    extra: dict[str, Any] = Field(default_factory=dict)
