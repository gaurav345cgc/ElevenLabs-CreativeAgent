"""Tests for LangGraph pipeline routing and per-stage retry."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID

import pytest

from pipeline_orchestrator.config import OrchestratorSettings
from pipeline_orchestrator.errors import build_failure, is_quota_error
from pipeline_orchestrator.nodes import route_entry, run_enhance, run_tts
from pipeline_orchestrator.state import initial_state


@pytest.fixture
def settings() -> OrchestratorSettings:
    return OrchestratorSettings(
        api_base_url="https://example.test",
        api_key="test-key",
        tenant_id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        poll_seconds=0.01,
        enhancement_timeout_seconds=1,
        tts_timeout_seconds=1,
        max_enhance_retries=2,
        max_tts_retries=2,
    )


def test_route_starts_at_compose_without_ids(settings: OrchestratorSettings) -> None:
    client = MagicMock()
    state = initial_state()
    result = route_entry(state, client=client)
    assert result["stage"] == "compose"
    client.get_transcript.assert_not_called()


def test_route_resumes_enhance_on_failed_transcript(settings: OrchestratorSettings) -> None:
    client = MagicMock()
    client.get_transcript.return_value = {
        "status": "FAILED_ENHANCEMENT",
        "last_error": "timeout",
    }
    state = initial_state(transcript_id="11111111-1111-1111-1111-111111111111")
    result = route_entry(state, client=client)
    assert result["stage"] == "enhance"


def test_route_resumes_tts_when_enhanced(settings: OrchestratorSettings) -> None:
    client = MagicMock()
    client.get_transcript.return_value = {"status": "ENHANCED"}
    state = initial_state(transcript_id="11111111-1111-1111-1111-111111111111")
    result = route_entry(state, client=client)
    assert result["stage"] == "tts"


def test_enhance_retries_agent2_only(settings: OrchestratorSettings) -> None:
    client = MagicMock()
    client.get_transcript.return_value = {
        "status": "FAILED_ENHANCEMENT",
        "last_error": "model error",
    }
    client.retry_enhancement.return_value = {"status": "PENDING_ENHANCEMENT"}
    state = initial_state(transcript_id="11111111-1111-1111-1111-111111111111")
    result = run_enhance(state, client=client, settings=settings)
    assert result["enhance_attempts"] == 1
    client.retry_enhancement.assert_called_once()
    client.compose_transcript.assert_not_called()


def test_tts_reenqueues_without_new_transcript(settings: OrchestratorSettings) -> None:
    client = MagicMock()
    client.list_versions.return_value = {
        "versions": [{"version_kind": "ELEVENLABS_ENHANCED", "version_id": "22222222-2222-2222-2222-222222222222"}]
    }
    client.create_audio_job.return_value = {
        "audio_job_id": "33333333-3333-3333-3333-333333333333",
        "status": "CREATED",
        "created": False,
    }
    state = {
        **initial_state(transcript_id="11111111-1111-1111-1111-111111111111"),
        "audio_job_id": "33333333-3333-3333-3333-333333333333",
        "last_audio_status": "REVIEW_REQUIRED",
        "tts_reenqueue": True,
        "tts_attempts": 1,
    }
    client.resolve_audio_job_last_error.return_value = None
    client.wait_for_audio_job.return_value = {
        "status": "COMPLETED",
        "completed_chunks": 12,
        "total_chunks": 12,
        "failed_chunks": 0,
    }
    result = run_tts(state, client=client, settings=settings)
    assert result["tts_attempts"] == 2
    assert result["stage"] == "download"
    client.create_audio_job.assert_called_once()
    client.wait_for_audio_job.assert_called_once()


def test_tts_does_not_spam_enqueue_on_review_required_resume(settings: OrchestratorSettings) -> None:
    client = MagicMock()
    client.list_versions.return_value = {
        "versions": [{"version_kind": "ELEVENLABS_ENHANCED", "version_id": "22222222-2222-2222-2222-222222222222"}]
    }
    client.resolve_audio_job_last_error.return_value = (
        "ElevenLabs quota insufficient: need ~5162 credits, only 86 remain"
    )
    client.wait_for_audio_job.return_value = {
        "status": "REVIEW_REQUIRED",
        "completed_chunks": 0,
        "total_chunks": 14,
        "failed_chunks": 0,
        "last_error": "ElevenLabs quota insufficient: need ~5162 credits, only 86 remain",
    }
    state = {
        **initial_state(transcript_id="11111111-1111-1111-1111-111111111111"),
        "audio_job_id": "33333333-3333-3333-3333-333333333333",
        "last_audio_status": "REVIEW_REQUIRED",
        "tts_attempts": 0,
    }
    result = run_tts(state, client=client, settings=settings)
    assert result["stage"] == "failed"
    assert "quota" in (result.get("last_error") or "").lower()
    client.create_audio_job.assert_not_called()


def test_tts_poll_logs_do_not_crash_on_review_required(settings: OrchestratorSettings) -> None:
    client = MagicMock()
    client.list_versions.return_value = {
        "versions": [{"version_kind": "ELEVENLABS_ENHANCED", "version_id": "22222222-2222-2222-2222-222222222222"}]
    }

    def _poll(payload: dict) -> None:
        pass

    client.wait_for_audio_job.side_effect = lambda *args, on_poll=None, **kwargs: (
        on_poll(
            {
                "status": "CREATED",
                "completed_chunks": 0,
                "total_chunks": 12,
                "failed_chunks": 0,
            }
        )
        if on_poll
        else None,
        {
            "status": "REVIEW_REQUIRED",
            "completed_chunks": 0,
            "total_chunks": 12,
            "failed_chunks": 0,
            "last_error": None,
        },
    )[-1]
    client.resolve_audio_job_last_error.return_value = None

    state = {
        **initial_state(transcript_id="11111111-1111-1111-1111-111111111111"),
        "audio_job_id": "33333333-3333-3333-3333-333333333333",
        "last_audio_status": "CREATED",
        "tts_attempts": 0,
    }
    result = run_tts(state, client=client, settings=settings)
    assert result["stage"] == "tts"
    assert result.get("tts_reenqueue") is True
    assert any("REVIEW_REQUIRED" in entry for entry in result["log"])
    client.create_audio_job.assert_not_called()


def test_tts_fails_fast_on_quota_from_poll(settings: OrchestratorSettings) -> None:
    client = MagicMock()
    client.list_versions.return_value = {
        "versions": [{"version_kind": "ELEVENLABS_ENHANCED", "version_id": "22222222-2222-2222-2222-222222222222"}]
    }
    client.resolve_audio_job_last_error.return_value = (
        "ElevenLabs quota insufficient: need ~5162 credits, only 86 remain"
    )
    client.wait_for_audio_job.return_value = {
        "status": "REVIEW_REQUIRED",
        "completed_chunks": 0,
        "total_chunks": 14,
        "failed_chunks": 0,
        "last_error": "ElevenLabs quota insufficient: need ~5162 credits, only 86 remain",
    }
    state = {
        **initial_state(transcript_id="11111111-1111-1111-1111-111111111111"),
        "audio_job_id": "33333333-3333-3333-3333-333333333333",
        "last_audio_status": "CREATED",
        "tts_attempts": 0,
    }
    result = run_tts(state, client=client, settings=settings)
    assert result["stage"] == "failed"
    assert result["failed_agent"] == "tts"
    assert "quota" in (result.get("last_error") or "").lower()
    client.create_audio_job.assert_not_called()


def test_quota_error_detected() -> None:
    assert is_quota_error("ElevenLabs quota_exceeded: 194 credits remain")
    assert not is_quota_error("connection reset")


def test_transient_third_party_error_detected() -> None:
    from pipeline_orchestrator.errors import is_transient_third_party_error, retry_limit_for_error

    assert is_transient_third_party_error("Service Unavailable", status_code=503)
    assert is_transient_third_party_error("connection reset by peer")
    assert not is_transient_third_party_error("invalid wound_id", status_code=400)
    assert not is_transient_third_party_error("quota_exceeded: 0 credits remain")
    assert retry_limit_for_error(2, third_party_extra=3, message="503 Service Unavailable", status_code=503) == 5
    assert retry_limit_for_error(2, third_party_extra=3, message="bad request", status_code=400) == 2


def test_failure_report_names_agent() -> None:
    failure = build_failure(
        "tts",
        "TTS ended with REVIEW_REQUIRED",
        transcript_id="11111111-1111-1111-1111-111111111111",
        audio_job_id="22222222-2222-2222-2222-222222222222",
        last_error="quota_exceeded",
    )
    report = failure.format_report()
    assert "Agent 3" in report
    assert "elevenlabs.io" in report.lower()
    assert "11111111" in report
    assert "audit.ps1" in report
