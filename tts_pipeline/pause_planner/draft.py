"""Draft OpenAI pause plan for Script Hub preview (cached on version metadata)."""

from __future__ import annotations

import logging
from typing import Any

from models.records import TranscriptAudioJobRecord, TranscriptVersionRecord
from tts_pipeline.chunk_planner.planner import estimate_chunk_duration_ms
from tts_pipeline.pause_planner.anchors import extract_pause_anchors
from tts_pipeline.pause_planner.density import enforce_pause_density
from tts_pipeline.pause_planner.human_markers import (
    DRAFT_PAUSE_PLAN_KEY,
    load_human_pause_plan,
)
from tts_pipeline.pause_planner.openai_client import OpenAIPausePlannerClient
from tts_pipeline.pause_planner.policy import (
    PAUSE_POLICY_VERSION,
    PROMPT_VERSION,
    normalize_pause_plan,
    validate_pause_plan_anchors,
)
from tts_pipeline.pause_planner.prompt import parse_pause_plan_response
from tts_pipeline.pause_planner.schema import PausePlan, PausePlannerProvider
from tts_pipeline.pause_planner.service import PAUSE_PLAN_KEY

logger = logging.getLogger("creative_agent.tts.pause_planner")

DEFAULT_DRAFT_TARGET_SECONDS = 300


def load_draft_pause_plan(metadata_json: dict[str, Any] | None) -> PausePlan | None:
    if not isinstance(metadata_json, dict):
        return None
    raw = metadata_json.get(DRAFT_PAUSE_PLAN_KEY)
    if raw is None:
        return None
    if isinstance(raw, PausePlan):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return PausePlan.model_validate(raw)
    except Exception:  # noqa: BLE001
        return None


def resolve_preview_pause_plan(
    metadata_json: dict[str, Any] | None,
) -> PausePlan | None:
    """Human overrides draft for Script Hub marker rendering."""
    human = load_human_pause_plan(metadata_json)
    if human is not None and human.holds:
        return human
    return load_draft_pause_plan(metadata_json)


def pause_plan_from_audio_job(job: TranscriptAudioJobRecord | None) -> PausePlan | None:
    if job is None:
        return None
    raw = (job.metadata_json or {}).get(PAUSE_PLAN_KEY)
    if raw is None:
        return None
    if isinstance(raw, PausePlan):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return PausePlan.model_validate(raw)
    except Exception:  # noqa: BLE001
        return None


def create_local_draft_pause_plan(
    version: TranscriptVersionRecord,
    *,
    target_duration_seconds: int | None = None,
) -> PausePlan:
    """Fast Script Hub draft: density holds only (no OpenAI). Avoids API Gateway timeouts."""
    anchors = extract_pause_anchors(version)
    target = target_duration_seconds or _target_duration_seconds(version)
    estimated_actual = max(0, estimate_chunk_duration_ms(version.content_text or "") // 1000)
    empty = PausePlan(
        planner=PausePlannerProvider.LOCAL,
        model="local-density",
        prompt_version=PROMPT_VERSION,
        policy_version=PAUSE_POLICY_VERSION,
        target_duration_seconds=target,
        estimated_speech_seconds=estimated_actual,
        total_hold_seconds=0,
        holds=[],
    )
    plan = enforce_pause_density(empty, anchors)
    return normalize_pause_plan(
        plan,
        target_duration_seconds=target,
        estimated_speech_seconds=estimated_actual,
    )


def create_draft_pause_plan(
    version: TranscriptVersionRecord,
    *,
    client: OpenAIPausePlannerClient | None = None,
    target_duration_seconds: int | None = None,
) -> PausePlan:
    """Call OpenAI (same path as TTS PlanPauses) and return a normalized draft."""
    anchors = extract_pause_anchors(version)
    target = target_duration_seconds or _target_duration_seconds(version)
    estimated_actual = max(0, estimate_chunk_duration_ms(version.content_text or "") // 1000)
    # Prompt the model with the coordinated speech budget when present so
    # hold_budget_seconds > 0 even if the script overshot the word ceiling.
    estimated_for_prompt = _estimated_speech_for_prompt(version, estimated_actual)

    planner = client or OpenAIPausePlannerClient()
    raw = planner.plan_pauses(
        beats=list(anchors.beats),
        paragraphs=list(anchors.paragraphs),
        target_duration_seconds=target,
        estimated_speech_seconds=estimated_for_prompt,
    )
    use_beats = anchors.preferred == "beats"
    plan = parse_pause_plan_response(
        raw,
        model=planner.model,
        target_duration_seconds=target,
        estimated_speech_seconds=estimated_actual,
        use_beats=use_beats,
    )
    validate_pause_plan_anchors(
        plan,
        beat_count=len(anchors.beats),
        paragraph_count=len(anchors.paragraphs),
    )
    plan = enforce_pause_density(plan, anchors)
    return normalize_pause_plan(
        plan,
        target_duration_seconds=target,
        estimated_speech_seconds=estimated_actual,
    )


def _target_duration_seconds(version: TranscriptVersionRecord) -> int:
    """Wall-clock session target — never confuse with speech duration_estimate."""
    meta = version.metadata_json or {}
    for source in (meta, meta.get("brief") if isinstance(meta.get("brief"), dict) else {}):
        if not isinstance(source, dict):
            continue
        if source.get("target_duration_seconds") is not None:
            return max(1, int(source["target_duration_seconds"]))
        if source.get("target_duration_minutes") is not None:
            return max(1, int(source["target_duration_minutes"]) * 60)
    return DEFAULT_DRAFT_TARGET_SECONDS


def _estimated_speech_for_prompt(
    version: TranscriptVersionRecord,
    estimated_actual_seconds: int,
) -> int:
    """Prefer Agent 1 speech budget for planner hold-budget math when available."""
    meta = version.metadata_json or {}
    raw = meta.get("speech_budget_seconds")
    if raw is None:
        return estimated_actual_seconds
    try:
        budget = max(0, int(raw))
    except (TypeError, ValueError):
        return estimated_actual_seconds
    return budget if budget > 0 else estimated_actual_seconds
