"""Intelligent resume: pick the exact next stage from checkpoint + live API status."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pipeline_orchestrator.client import CreativeAgentApiError, CreativeAgentClient
from pipeline_orchestrator.state import (
    ENHANCE_FAILURE_STATUSES,
    ENHANCE_IN_PROGRESS_STATUSES,
    ENHANCE_SUCCESS_STATUSES,
    TTS_IN_PROGRESS_STATUSES,
    TTS_RETRYABLE_STATUSES,
    TTS_SUCCESS_STATUS,
    PipelineState,
)


def resolve_resume_cursor(
    state: PipelineState,
    *,
    client: CreativeAgentClient,
) -> PipelineState:
    """Inspect IDs + live status and set ``stage`` to the exact place to continue.

    Order of preference:
    1. audio job → download / tts
    2. transcript → enhance / tts / done
    3. else → compose
    """
    correlation_id = state.get("correlation_id")
    # Log deltas only (LangGraph / agentic append; do not replay full history).
    notes: list[str] = ["resume: resolving cursor from live status"]
    updates: dict[str, Any] = {}

    audio_job_id = state.get("audio_job_id")
    if audio_job_id and not state.get("skip_tts"):
        try:
            job = client.get_audio_job(UUID(audio_job_id), correlation_id=correlation_id)
        except CreativeAgentApiError as exc:
            updates["last_error"] = str(exc)
            updates["stage"] = "tts"
            notes.append(f"resume: audio job fetch failed; will retry TTS ({exc})")
            updates["log"] = notes
            return {**state, **updates}

        status = job.get("status")
        updates["last_audio_status"] = status
        updates["last_error"] = client.resolve_audio_job_last_error(
            UUID(audio_job_id),
            correlation_id=correlation_id,
            cached=job.get("last_error"),
        )
        if job.get("transcript_id"):
            updates["transcript_id"] = str(job.get("transcript_id"))
        if job.get("transcript_version_id"):
            updates["transcript_version_id"] = str(job.get("transcript_version_id"))

        if status == TTS_SUCCESS_STATUS:
            if state.get("local_mp3_path"):
                updates["stage"] = "done"
                notes.append("resume: audio COMPLETED and MP3 on disk")
            else:
                updates["stage"] = "download"
                notes.append("resume: audio COMPLETED → download")
            updates["log"] = notes
            return {**state, **updates}

        if status in TTS_RETRYABLE_STATUSES | TTS_IN_PROGRESS_STATUSES | {
            "CREATED",
            "PLANNING",
            "READY",
            "GENERATING",
        }:
            updates["stage"] = "tts"
            notes.append(f"resume: audio {status} → tts")
            updates["log"] = notes
            return {**state, **updates}

        updates["stage"] = "tts"
        notes.append(f"resume: audio {status} → tts (fallback)")
        updates["log"] = notes
        return {**state, **updates}

    transcript_id = state.get("transcript_id")
    if transcript_id:
        try:
            tx = client.get_transcript(UUID(transcript_id), correlation_id=correlation_id)
        except CreativeAgentApiError as exc:
            updates["last_error"] = str(exc)
            updates["stage"] = "enhance"
            notes.append(f"resume: transcript fetch failed; will retry enhance ({exc})")
            updates["log"] = notes
            return {**state, **updates}

        status = tx.get("status")
        updates["last_transcript_status"] = status

        if status in ENHANCE_SUCCESS_STATUSES:
            if state.get("skip_tts"):
                updates["stage"] = "done"
                notes.append(f"resume: transcript {status}, skip_tts → done")
            else:
                updates["stage"] = "tts"
                notes.append(f"resume: transcript {status} → tts")
            updates["log"] = notes
            return {**state, **updates}

        if status in ENHANCE_FAILURE_STATUSES | ENHANCE_IN_PROGRESS_STATUSES:
            updates["stage"] = "enhance"
            notes.append(f"resume: transcript {status} → enhance")
            updates["log"] = notes
            return {**state, **updates}

        # Unknown / early status — still try enhance rather than recompose
        updates["stage"] = "enhance"
        notes.append(
            f"resume: transcript {status} → enhance (safe default; will not recompose)"
        )
        updates["log"] = notes
        return {**state, **updates}

    if state.get("qa_report"):
        updates["stage"] = "qa_repair"
        notes.append("resume: qa_report present → qa_repair")
        updates["log"] = notes
        return {**state, **updates}

    updates["stage"] = "compose"
    notes.append("resume: no IDs → compose")
    updates["log"] = notes
    return {**state, **updates}
