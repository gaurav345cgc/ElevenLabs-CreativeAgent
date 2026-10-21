"""Pipeline orchestrator logging helpers."""

from __future__ import annotations

import logging
from typing import Any

from observability.logging import log_orchestrator_event
from pipeline_orchestrator.state import PipelineState

logger = logging.getLogger("creative_agent.orchestrator")


def pipeline_context(state: PipelineState) -> dict[str, Any]:
    return {
        k: v
        for k, v in {
            "correlation_id": state.get("correlation_id"),
            "transcript_id": state.get("transcript_id"),
            "transcript_version_id": state.get("transcript_version_id"),
            "audio_job_id": state.get("audio_job_id"),
            "stage": state.get("stage"),
            "last_transcript_status": state.get("last_transcript_status"),
            "last_audio_status": state.get("last_audio_status"),
        }.items()
        if v is not None
    }


def log_pipeline_step(
    state: PipelineState,
    message: str,
    *,
    event_type: str = "pipeline_step",
    level: int = logging.INFO,
    **extra: Any,
) -> list[str]:
    log_orchestrator_event(
        message,
        level=level,
        event_type=event_type,
        **pipeline_context(state),
        **extra,
    )
    return [message]


def log_pipeline_error(
    state: PipelineState,
    message: str,
    *,
    event_type: str = "pipeline_error",
    **extra: Any,
) -> list[str]:
    log_orchestrator_event(
        message,
        level=logging.ERROR,
        event_type=event_type,
        **pipeline_context(state),
        **extra,
    )
    return [message]
