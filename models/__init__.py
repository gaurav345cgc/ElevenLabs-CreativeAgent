"""Shared DTOs, enums, and domain types."""

from models.agents import Agent1Output, Agent2Output
from models.common import (
    SCHEMA_VERSION,
    build_enhancement_idempotency_key,
    utc_now,
)
from models.enums import EnhancementMode, TranscriptStatus, VersionKind
from models.errors import ErrorCode, ErrorEnvelope
from models.messages import EnhancementJobMessage
from models.metadata import (
    DurationEstimate,
    EnhancedScriptContent,
    EnhancedVersionMetadata,
    NarrationChunk,
    PatternSlotSelection,
    RawPatternMetadata,
    ScriptSection,
    SectionedScriptContent,
    SelectedPatternPlan,
    TaxonomyContext,
    VoiceModelTarget,
)
from models.records import TranscriptJobEventRecord, TranscriptRecord, TranscriptVersionRecord
from models.requests import CreateTranscriptRequest
from models.validation import (
    COMPOSITION_SLOTS,
    TaxonomyValidationError,
    build_example_pattern_plan,
    validate_pattern_plan,
    validate_taxonomy_combination,
)

__all__ = [
    "SCHEMA_VERSION",
    "Agent1Output",
    "Agent2Output",
    "COMPOSITION_SLOTS",
    "CreateTranscriptRequest",
    "DurationEstimate",
    "EnhancedScriptContent",
    "EnhancedVersionMetadata",
    "EnhancementJobMessage",
    "EnhancementMode",
    "ErrorCode",
    "ErrorEnvelope",
    "NarrationChunk",
    "PatternSlotSelection",
    "RawPatternMetadata",
    "ScriptSection",
    "SectionedScriptContent",
    "SelectedPatternPlan",
    "TaxonomyContext",
    "TaxonomyValidationError",
    "TranscriptJobEventRecord",
    "TranscriptRecord",
    "TranscriptStatus",
    "TranscriptVersionRecord",
    "VersionKind",
    "VoiceModelTarget",
    "build_enhancement_idempotency_key",
    "build_example_pattern_plan",
    "utc_now",
    "validate_pattern_plan",
    "validate_taxonomy_combination",
]
