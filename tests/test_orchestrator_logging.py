"""Orchestrator structured logging tests."""

from __future__ import annotations

import pytest

from observability.logging import configure_orchestrator_logging, log_orchestrator_event, orchestrator_logger
from pipeline_orchestrator.logging_util import log_pipeline_step
from pipeline_orchestrator.state import initial_state


@pytest.fixture(autouse=True)
def _reset_orchestrator_logger() -> None:
    orchestrator_logger.handlers.clear()
    import observability.logging as logging_module

    logging_module._orchestrator_plain_logs = False


def test_log_orchestrator_event_plain_mode(capsys) -> None:
    configure_orchestrator_logging(human_readable=True)
    log_orchestrator_event(
        "pipeline run started",
        event_type="run_start",
        correlation_id="corr-1",
    )
    captured = capsys.readouterr()
    assert "pipeline run started" in captured.err
    assert "corr-1" in captured.err


def test_log_pipeline_step_includes_context() -> None:
    configure_orchestrator_logging(human_readable=True)
    state = initial_state(transcript_id="11111111-1111-1111-1111-111111111111")
    lines = log_pipeline_step(state, "compose complete")
    assert lines == ["compose complete"]
