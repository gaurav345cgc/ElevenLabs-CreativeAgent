"""Structured models for pattern index and examples corpus."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PatternFamilyEntry(BaseModel):
    pattern_family: str
    family: str = ""
    composition_slot: str
    placement: str
    canonical_pattern: str = ""
    wound_ids: list[str]
    generation_codes: list[str]
    stage_numbers: list[int]
    pillar_codes: list[str]
    instruction_rule: str
    use_case: str
    tone_notes: str


class PatternIndexDocument(BaseModel):
    schema_version: str
    composition_slots: list[str]
    default_pattern_by_slot: dict[str, str]
    patterns: list[PatternFamilyEntry]


class MeditationExampleEntry(BaseModel):
    example_id: str
    generation_code: str
    wound_id: str
    stage_no: int
    pillar_code: str | None = None
    pattern_family: str
    pattern_group: str = ""
    placement: str
    pattern_guidance: str = ""
    use_case: str
    tone_notes: str
    reference_excerpt: str


class ExamplesDocument(BaseModel):
    schema_version: str
    examples: list[MeditationExampleEntry]


class PatternSelectionContext(BaseModel):
    generation_code: str
    wound_id: str
    stage_no: int
    pillar_code: str | None = None
    content_type: str = "guided_meditation"


class RankedExample(BaseModel):
    example: MeditationExampleEntry
    score: int
    match_tier: str = Field(description="exact | relaxed | fallback")
