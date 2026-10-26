"""Intelligent resume cursor — continue from the exact leftover stage."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from pipeline_orchestrator.resume import resolve_resume_cursor
from pipeline_orchestrator.state import initial_state


def test_resume_enhanced_goes_to_tts() -> None:
    tid = str(uuid4())
    client = MagicMock()
    client.get_transcript.return_value = {"status": "ENHANCED"}
    state = {**initial_state(transcript_id=tid), "transcript_id": tid}
    result = resolve_resume_cursor(state, client=client)
    assert result["stage"] == "tts"
    assert result["last_transcript_status"] == "ENHANCED"
    client.compose_transcript.assert_not_called()


def test_resume_audio_completed_goes_to_download() -> None:
    aid = str(uuid4())
    client = MagicMock()
    client.get_audio_job.return_value = {
        "status": "COMPLETED",
        "transcript_id": str(uuid4()),
        "transcript_version_id": str(uuid4()),
        "last_error": None,
    }
    client.resolve_audio_job_last_error.return_value = None
    state = {**initial_state(audio_job_id=aid), "audio_job_id": aid}
    result = resolve_resume_cursor(state, client=client)
    assert result["stage"] == "download"


def test_resume_pending_enhancement_stays_on_enhance() -> None:
    tid = str(uuid4())
    client = MagicMock()
    client.get_transcript.return_value = {"status": "PENDING_ENHANCEMENT"}
    state = {**initial_state(transcript_id=tid), "transcript_id": tid}
    result = resolve_resume_cursor(state, client=client)
    assert result["stage"] == "enhance"


def test_resume_without_ids_starts_compose() -> None:
    client = MagicMock()
    result = resolve_resume_cursor(initial_state(), client=client)
    assert result["stage"] == "compose"
    client.get_transcript.assert_not_called()
