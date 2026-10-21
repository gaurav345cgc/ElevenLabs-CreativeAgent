"""Shared LangGraph state for the end-to-end pipeline."""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from typing_extensions import NotRequired

PipelineStage = Literal[
    "route",
    "compose",
    "enhance",
    "tts",
    "download",
    "done",
    "failed",
]

TERMINAL_STAGES = frozenset({"done", "failed"})

ENHANCE_FAILURE_STATUSES = frozenset({"FAILED_ENHANCEMENT", "REVIEW_REQUIRED"})
ENHANCE_IN_PROGRESS_STATUSES = frozenset({"PENDING_ENHANCEMENT", "ENHANCING", "CREATED"})
ENHANCE_SUCCESS_STATUS = "APPROVED"

TTS_SUCCESS_STATUS = "COMPLETED"
TTS_RETRYABLE_STATUSES = frozenset({"REVIEW_REQUIRED", "FAILED", "PARTIALLY_FAILED"})
TTS_IN_PROGRESS_STATUSES = frozenset(
    {"CREATED", "PLANNING", "READY", "GENERATING", "PARTIALLY_FAILED"}
)


class PipelineState(TypedDict):
    """Checkpointed orchestration state — resume from any completed stage."""

    stage: PipelineStage
    correlation_id: NotRequired[str | None]

    transcript_id: NotRequired[str | None]
    transcript_version_id: NotRequired[str | None]
    audio_job_id: NotRequired[str | None]
    local_mp3_path: NotRequired[str | None]

    compose_attempts: NotRequired[int]
    enhance_attempts: NotRequired[int]
    tts_attempts: NotRequired[int]
    tts_reenqueue: NotRequired[bool]

    last_error: NotRequired[str | None]
    last_transcript_status: NotRequired[str | None]
    last_audio_status: NotRequired[str | None]

    failed_agent: NotRequired[str | None]
    fix_hint: NotRequired[str | None]

    skip_compose: NotRequired[bool]
    skip_tts: NotRequired[bool]

    log: Annotated[list[str], operator.add]


def initial_state(
    *,
    transcript_id: str | None = None,
    audio_job_id: str | None = None,
    skip_compose: bool = False,
    skip_tts: bool = False,
    correlation_id: str | None = None,
) -> PipelineState:
    return {
        "stage": "route",
        "correlation_id": correlation_id,
        "transcript_id": transcript_id,
        "audio_job_id": audio_job_id,
        "compose_attempts": 0,
        "enhance_attempts": 0,
        "tts_attempts": 0,
        "skip_compose": skip_compose,
        "skip_tts": skip_tts,
        "log": [],
    }
