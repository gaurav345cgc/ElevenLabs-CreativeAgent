"""One-job-at-a-time pipeline lock."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pipeline_orchestrator.run_lock import (
    PipelineBusyError,
    RunLock,
    acquire_run_lock,
    load_lock,
    release_run_lock,
)


def test_acquire_blocks_second_live_holder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pipeline_orchestrator.run_lock._pid_alive", lambda pid: True)
    first = acquire_run_lock(tmp_path, correlation_id="a")
    assert first.pid == os.getpid()

    # Pretend another process wrote the lock.
    other = RunLock(
        pid=first.pid + 99999,
        correlation_id="b",
        transcript_id=None,
        audio_job_id=None,
        started_at=first.started_at,
    )
    (tmp_path / ".pipeline_lock.json").write_text(
        '{"pid": %d, "correlation_id": "b", "transcript_id": null, '
        '"audio_job_id": null, "started_at": "%s"}' % (other.pid, other.started_at),
        encoding="utf-8",
    )

    with pytest.raises(PipelineBusyError) as exc:
        acquire_run_lock(tmp_path, correlation_id="c")
    assert "one job at a time" in str(exc.value).lower()


def test_stale_lock_stolen_when_pid_dead(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pipeline_orchestrator.run_lock._pid_alive", lambda pid: False)
    (tmp_path / ".pipeline_lock.json").write_text(
        '{"pid": 1, "correlation_id": "old", "transcript_id": null, '
        '"audio_job_id": null, "started_at": "2020-01-01T00:00:00+00:00"}',
        encoding="utf-8",
    )
    lock = acquire_run_lock(tmp_path, correlation_id="new")
    assert lock.pid == os.getpid()
    assert load_lock(tmp_path) is not None
    release_run_lock(tmp_path, expected_pid=os.getpid())
    assert load_lock(tmp_path) is None


def test_force_steals_live_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pipeline_orchestrator.run_lock._pid_alive", lambda pid: True)
    (tmp_path / ".pipeline_lock.json").write_text(
        '{"pid": 424242, "correlation_id": "busy", "transcript_id": null, '
        '"audio_job_id": null, "started_at": "2020-01-01T00:00:00+00:00"}',
        encoding="utf-8",
    )
    lock = acquire_run_lock(tmp_path, correlation_id="forced", force=True)
    assert lock.correlation_id == "forced"
