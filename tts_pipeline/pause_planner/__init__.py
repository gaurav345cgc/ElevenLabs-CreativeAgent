"""Meditation pause planning — structured holds for TTS stitch intercalation."""

from tts_pipeline.pause_planner.anchors import PauseAnchors, extract_pause_anchors
from tts_pipeline.pause_planner.density import (
    DEFAULT_MAX_SENTENCES,
    enforce_pause_density,
)
from tts_pipeline.pause_planner.errors import (
    PausePlannerError,
    PausePlannerTransientError,
    PausePlannerValidationError,
)
from tts_pipeline.pause_planner.human_markers import (
    DEFAULT_HUMAN_PAUSE_SECONDS,
    HUMAN_PAUSE_PLAN_KEY,
    HUMAN_PROMPT_VERSION,
    HumanPauseMarkerError,
    ParsedPauseMarkedText,
    build_human_pause_plan,
    build_pause_review_text,
    format_pause_marked_text,
    load_human_pause_plan,
    parse_pause_marked_text,
)
from tts_pipeline.pause_planner.mapping import map_pause_plan_to_chunks
from tts_pipeline.pause_planner.openai_client import (
    OpenAIPausePlannerClient,
    resolve_pause_planner_model,
)
from tts_pipeline.pause_planner.prompt import (
    build_system_prompt,
    build_user_prompt,
    parse_pause_plan_response,
)
from tts_pipeline.pause_planner.policy import (
    DEFAULT_FAIL_ON_PLANNER_ERROR,
    DEFAULT_TAIL_ESTIMATE_SECONDS,
    DURATION_TOLERANCE_RATIO,
    HOLD_JITTER_RATIO,
    KIND_BOUNDS,
    MAX_HOLD_SECONDS,
    MAX_HOLDS_PER_JOB,
    MIN_HOLD_SECONDS,
    PAUSE_POLICY_VERSION,
    PROMPT_VERSION,
    HoldKindBounds,
    clamp_hold_seconds,
    jitter_hold_seconds,
    normalize_pause_plan,
    validate_pause_plan_anchors,
)
from tts_pipeline.pause_planner.schema import (
    MappedPauseHold,
    MappedPausePlan,
    PauseHold,
    PauseHoldKind,
    PausePlan,
    PausePlannerProvider,
)
from tts_pipeline.pause_planner.service import (
    InMemoryPausePlanStore,
    SessionPausePlanStore,
    create_or_load_pause_plan,
    persist_mapped_pause_plan,
)

__all__ = [
    "DEFAULT_FAIL_ON_PLANNER_ERROR",
    "DEFAULT_HUMAN_PAUSE_SECONDS",
    "DEFAULT_MAX_SENTENCES",
    "DEFAULT_TAIL_ESTIMATE_SECONDS",
    "DURATION_TOLERANCE_RATIO",
    "HOLD_JITTER_RATIO",
    "HUMAN_PAUSE_PLAN_KEY",
    "HUMAN_PROMPT_VERSION",
    "KIND_BOUNDS",
    "MAX_HOLD_SECONDS",
    "MAX_HOLDS_PER_JOB",
    "MIN_HOLD_SECONDS",
    "PAUSE_POLICY_VERSION",
    "PROMPT_VERSION",
    "HoldKindBounds",
    "HumanPauseMarkerError",
    "InMemoryPausePlanStore",
    "MappedPauseHold",
    "MappedPausePlan",
    "OpenAIPausePlannerClient",
    "ParsedPauseMarkedText",
    "PauseAnchors",
    "PauseHold",
    "PauseHoldKind",
    "PausePlan",
    "PausePlannerError",
    "PausePlannerProvider",
    "PausePlannerTransientError",
    "PausePlannerValidationError",
    "SessionPausePlanStore",
    "build_human_pause_plan",
    "build_pause_review_text",
    "build_system_prompt",
    "build_user_prompt",
    "clamp_hold_seconds",
    "create_or_load_pause_plan",
    "enforce_pause_density",
    "extract_pause_anchors",
    "format_pause_marked_text",
    "jitter_hold_seconds",
    "load_human_pause_plan",
    "map_pause_plan_to_chunks",
    "normalize_pause_plan",
    "parse_pause_marked_text",
    "parse_pause_plan_response",
    "persist_mapped_pause_plan",
    "resolve_pause_planner_model",
    "validate_pause_plan_anchors",
]
