"""Single-flight lock: only one pipeline job may run at a time."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from observability.logging import log_orchestrator_event

logger = logging.getLogger("creative_agent.orchestrator.lock")

LOCK_FILENAME = ".pipeline_lock.json"


class PipelineBusyError(RuntimeError):
    """Raised when another pipeline job is already in progress."""

    def __init__(self, message: str, *, lock: "RunLock | None" = None) -> None:
        super().__init__(message)
        self.lock = lock


@dataclass
class RunLock:
    pid: int
    correlation_id: str | None
    transcript_id: str | None
    audio_job_id: str | None
    started_at: str
    hostname: str | None = None

    def format_busy_message(self) -> str:
        parts = [
            "Another pipeline job is already in progress (one job at a time).",
            f"  pid: {self.pid}",
            f"  started_at: {self.started_at}",
        ]
        if self.correlation_id:
            parts.append(f"  correlation_id: {self.correlation_id}")
        if self.transcript_id:
            parts.append(f"  transcript_id: {self.transcript_id}")
        if self.audio_job_id:
            parts.append(f"  audio_job_id: {self.audio_job_id}")
        parts.append("Wait for it to finish, or resume the same run (omit --fresh).")
        parts.append("Only use --force-new if you are sure the other process is dead.")
        return "\n".join(parts)


def lock_path(output_dir: Path) -> Path:
    return output_dir / LOCK_FILENAME


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        # Windows + Unix: signal 0 checks existence without killing.
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we cannot signal it.
        return True
    except OSError:
        return False
    return True


def load_lock(output_dir: Path) -> RunLock | None:
    path = lock_path(output_dir)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return RunLock(
            pid=int(payload["pid"]),
            correlation_id=payload.get("correlation_id"),
            transcript_id=payload.get("transcript_id"),
            audio_job_id=payload.get("audio_job_id"),
            started_at=str(payload.get("started_at") or ""),
            hostname=payload.get("hostname"),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _write_lock(output_dir: Path, lock: RunLock) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = lock_path(output_dir)
    path.write_text(json.dumps(asdict(lock), indent=2), encoding="utf-8")


def release_run_lock(output_dir: Path, *, expected_pid: int | None = None) -> None:
    path = lock_path(output_dir)
    if not path.is_file():
        return
    if expected_pid is not None:
        current = load_lock(output_dir)
        if current is not None and current.pid != expected_pid:
            return
    path.unlink(missing_ok=True)
    log_orchestrator_event(
        "released pipeline run lock",
        event_type="run_lock_released",
        path=str(path),
        pid=expected_pid,
    )


def update_run_lock(
    output_dir: Path,
    *,
    correlation_id: str | None = None,
    transcript_id: str | None = None,
    audio_job_id: str | None = None,
) -> None:
    """Refresh lock metadata as the job progresses (same pid)."""
    current = load_lock(output_dir)
    if current is None or current.pid != os.getpid():
        return
    updated = RunLock(
        pid=current.pid,
        correlation_id=correlation_id or current.correlation_id,
        transcript_id=transcript_id or current.transcript_id,
        audio_job_id=audio_job_id or current.audio_job_id,
        started_at=current.started_at,
        hostname=current.hostname,
    )
    _write_lock(output_dir, updated)


def acquire_run_lock(
    output_dir: Path,
    *,
    correlation_id: str | None = None,
    force: bool = False,
) -> RunLock:
    """Acquire exclusive job lock. Raises PipelineBusyError if another live job holds it."""
    import socket

    existing = load_lock(output_dir)
    if existing is not None:
        if existing.pid == os.getpid():
            return existing
        if _pid_alive(existing.pid) and not force:
            raise PipelineBusyError(existing.format_busy_message(), lock=existing)
        # Stale lock (dead process) — take over.
        log_orchestrator_event(
            "stealing stale pipeline run lock",
            level=logging.WARNING,
            event_type="run_lock_stale",
            stale_pid=existing.pid,
            path=str(lock_path(output_dir)),
        )

    lock = RunLock(
        pid=os.getpid(),
        correlation_id=correlation_id,
        transcript_id=None,
        audio_job_id=None,
        started_at=datetime.now(UTC).isoformat(),
        hostname=socket.gethostname(),
    )
    _write_lock(output_dir, lock)
    log_orchestrator_event(
        "acquired pipeline run lock",
        event_type="run_lock_acquired",
        pid=lock.pid,
        correlation_id=correlation_id,
        path=str(lock_path(output_dir)),
    )
    return lock
