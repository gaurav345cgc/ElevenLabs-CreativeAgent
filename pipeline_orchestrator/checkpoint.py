"""Persist pipeline run IDs so the next invocation can resume automatically."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from observability.logging import log_orchestrator_event
from pipeline_orchestrator.client import CreativeAgentClient
from pipeline_orchestrator.state import (
    ENHANCE_FAILURE_STATUSES,
    ENHANCE_IN_PROGRESS_STATUSES,
    ENHANCE_SUCCESS_STATUSES,
    TTS_IN_PROGRESS_STATUSES,
    TTS_RETRYABLE_STATUSES,
    TTS_SUCCESS_STATUS,
    PipelineState,
)

CHECKPOINT_FILENAME = ".pipeline_run.json"


@dataclass
class PipelineCheckpoint:
    transcript_id: str | None = None
    transcript_version_id: str | None = None
    audio_job_id: str | None = None
    correlation_id: str | None = None
    local_mp3_path: str | None = None
    stage: str | None = None
    updated_at: str | None = None
    # Resume continuity (optional — older checkpoints omit these)
    repair_attempts: int | None = None
    compose_attempts: int | None = None
    enhance_attempts: int | None = None
    tts_attempts: int | None = None
    last_transcript_status: str | None = None
    last_audio_status: str | None = None
    compose_brief: dict | None = None
    skip_tts: bool | None = None

    @classmethod
    def from_state(cls, state: PipelineState) -> PipelineCheckpoint:
        brief = state.get("compose_brief")
        return cls(
            transcript_id=state.get("transcript_id"),
            transcript_version_id=state.get("transcript_version_id"),
            audio_job_id=state.get("audio_job_id"),
            correlation_id=state.get("correlation_id"),
            local_mp3_path=state.get("local_mp3_path"),
            stage=state.get("stage"),
            updated_at=datetime.now(UTC).isoformat(),
            repair_attempts=state.get("repair_attempts"),
            compose_attempts=state.get("compose_attempts"),
            enhance_attempts=state.get("enhance_attempts"),
            tts_attempts=state.get("tts_attempts"),
            last_transcript_status=state.get("last_transcript_status"),
            last_audio_status=state.get("last_audio_status"),
            compose_brief=dict(brief) if isinstance(brief, dict) else None,
            skip_tts=bool(state.get("skip_tts")) if state.get("skip_tts") is not None else None,
        )


def checkpoint_path(output_dir: Path) -> Path:
    return output_dir / CHECKPOINT_FILENAME


def load_checkpoint(output_dir: Path) -> PipelineCheckpoint | None:
    path = checkpoint_path(output_dir)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("checkpoint root must be an object")
        # Tolerate older checkpoint files with fewer fields.
        known = {f.name for f in fields(PipelineCheckpoint)}
        filtered = {k: v for k, v in payload.items() if k in known}
        checkpoint = PipelineCheckpoint(**filtered)
        log_orchestrator_event(
            "loaded pipeline checkpoint",
            event_type="checkpoint_loaded",
            path=str(path),
            transcript_id=checkpoint.transcript_id,
            audio_job_id=checkpoint.audio_job_id,
            stage=checkpoint.stage,
        )
        return checkpoint
    except (json.JSONDecodeError, TypeError, ValueError):
        log_orchestrator_event(
            "checkpoint file unreadable",
            level=logging.WARNING,
            event_type="checkpoint_invalid",
            path=str(path),
        )
        return None


def save_checkpoint(output_dir: Path, state: PipelineState) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    cp = PipelineCheckpoint.from_state(state)
    path = checkpoint_path(output_dir)
    path.write_text(
        json.dumps(asdict(cp), indent=2),
        encoding="utf-8",
    )
    log_orchestrator_event(
        "saved pipeline checkpoint",
        event_type="checkpoint_saved",
        path=str(path),
        transcript_id=cp.transcript_id,
        audio_job_id=cp.audio_job_id,
        stage=cp.stage,
        correlation_id=cp.correlation_id,
    )


def clear_checkpoint(output_dir: Path) -> None:
    path = checkpoint_path(output_dir)
    if path.is_file():
        path.unlink()
        log_orchestrator_event(
            "cleared pipeline checkpoint",
            event_type="checkpoint_cleared",
            path=str(path),
        )


def is_run_finished(client: CreativeAgentClient, checkpoint: PipelineCheckpoint) -> bool:
    """True when the checkpoint represents a fully delivered MP3."""
    if checkpoint.local_mp3_path and Path(checkpoint.local_mp3_path).is_file():
        if not checkpoint.audio_job_id:
            return True
        try:
            job = client.get_audio_job(UUID(checkpoint.audio_job_id))
        except Exception:
            return True
        return job.get("status") == TTS_SUCCESS_STATUS

    if not checkpoint.audio_job_id and not checkpoint.transcript_id:
        return False

    if checkpoint.audio_job_id:
        try:
            job = client.get_audio_job(UUID(checkpoint.audio_job_id))
        except Exception:
            return False
        if job.get("status") == TTS_SUCCESS_STATUS:
            return bool(checkpoint.local_mp3_path and Path(checkpoint.local_mp3_path).is_file())
        return False

    if checkpoint.transcript_id:
        try:
            tx = client.get_transcript(UUID(checkpoint.transcript_id))
        except Exception:
            return False
        return (
            tx.get("status") in ENHANCE_SUCCESS_STATUSES
            and checkpoint.local_mp3_path is not None
        )

    return False


def is_run_resumable(client: CreativeAgentClient, checkpoint: PipelineCheckpoint) -> bool:
    """True when an incomplete job exists and should be continued."""
    if is_run_finished(client, checkpoint):
        return False

    if checkpoint.audio_job_id:
        try:
            job = client.get_audio_job(UUID(checkpoint.audio_job_id))
            status = job.get("status")
            if status == TTS_SUCCESS_STATUS:
                return True
            if status in TTS_RETRYABLE_STATUSES | TTS_IN_PROGRESS_STATUSES:
                return True
        except Exception:
            return True

    if checkpoint.transcript_id:
        try:
            tx = client.get_transcript(UUID(checkpoint.transcript_id))
            status = tx.get("status")
            if status in ENHANCE_SUCCESS_STATUSES:
                return True
            if status in ENHANCE_FAILURE_STATUSES | ENHANCE_IN_PROGRESS_STATUSES:
                return True
        except Exception:
            return True

    return bool(checkpoint.transcript_id or checkpoint.audio_job_id)


def state_from_checkpoint(checkpoint: PipelineCheckpoint) -> PipelineState:
    state: PipelineState = {
        "stage": "route",  # resolved to exact stage via resolve_resume_cursor
        "correlation_id": checkpoint.correlation_id,
        "transcript_id": checkpoint.transcript_id,
        "transcript_version_id": checkpoint.transcript_version_id,
        "audio_job_id": checkpoint.audio_job_id,
        "local_mp3_path": checkpoint.local_mp3_path,
        "compose_attempts": int(checkpoint.compose_attempts or 0),
        "repair_attempts": int(checkpoint.repair_attempts or 0),
        "enhance_attempts": int(checkpoint.enhance_attempts or 0),
        "tts_attempts": int(checkpoint.tts_attempts or 0),
        "skip_compose": bool(checkpoint.transcript_id),
        "skip_tts": bool(checkpoint.skip_tts) if checkpoint.skip_tts is not None else False,
        "qa_history": [],
        "decision_log": [],
        "brain_steps": 0,
        "log": [],
    }
    if checkpoint.last_transcript_status:
        state["last_transcript_status"] = checkpoint.last_transcript_status
    if checkpoint.last_audio_status:
        state["last_audio_status"] = checkpoint.last_audio_status
    if checkpoint.compose_brief:
        state["compose_brief"] = dict(checkpoint.compose_brief)
    return state
