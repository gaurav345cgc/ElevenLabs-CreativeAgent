"""Tests for operator-facing pipeline audit."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from uuid import UUID

from observability.pipeline_audit import (
    AuditCheck,
    CheckStatus,
    PipelineAuditReport,
    _overall_status,
    run_pipeline_audit,
)
from pipeline_orchestrator.checkpoint import PipelineCheckpoint
from pipeline_orchestrator.config import OrchestratorSettings


def _settings() -> OrchestratorSettings:
    return OrchestratorSettings(
        api_base_url="https://api.example.com",
        api_key="test-key",
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        output_dir=Path("output"),
    )


def test_overall_status_fail_beats_warn() -> None:
    checks = [
        AuditCheck("A", CheckStatus.OK, "ok"),
        AuditCheck("B", CheckStatus.WARN, "warn thing"),
        AuditCheck("C", CheckStatus.FAIL, "fail thing"),
    ]
    overall, headline = _overall_status(checks)
    assert overall == CheckStatus.FAIL
    assert headline == "fail thing"


def test_format_text_includes_actions_and_ids() -> None:
    report = PipelineAuditReport(
        generated_at=datetime(2026, 7, 6, 12, 0, tzinfo=UTC),
        overall=CheckStatus.FAIL,
        headline="Stopped — ElevenLabs credits exhausted",
        checks=(
            AuditCheck(
                "Audio job (Agent 3)",
                CheckStatus.FAIL,
                "Stopped — ElevenLabs credits exhausted",
                action="Top up at https://elevenlabs.io",
            ),
        ),
        transcript_id="t-1",
        audio_job_id="a-1",
    )
    text = report.format_text()
    assert "PIPELINE AUDIT" in text
    assert "FAIL" in text
    assert "Top up at https://elevenlabs.io" in text
    assert "transcript_id: t-1" in text
    assert "audit.ps1" in text


@patch("observability.pipeline_audit.load_checkpoint")
@patch("observability.pipeline_audit.httpx.get")
@patch("observability.pipeline_audit._check_elevenlabs_credits")
def test_run_pipeline_audit_quota_failure(
    mock_credits: MagicMock,
    mock_get: MagicMock,
    mock_checkpoint: MagicMock,
    tmp_path: Path,
) -> None:
    mock_checkpoint.return_value = PipelineCheckpoint(
        transcript_id="11111111-1111-1111-1111-111111111111",
        audio_job_id="22222222-2222-2222-2222-222222222222",
        stage="failed",
    )
    mock_credits.return_value = AuditCheck(
        "ElevenLabs credits",
        CheckStatus.FAIL,
        "Not enough credits",
        action="Top up",
    )

    def handler(url: str, **kwargs: object) -> httpx.Response:
        request = httpx.Request("GET", url)
        if "/health" in url:
            return httpx.Response(200, json={"checks": {"db": {"ok": True}}}, request=request)
        if "/transcripts/" in url:
            return httpx.Response(200, json={"status": "ENHANCED"}, request=request)
        if "/audio-jobs/" in url:
            return httpx.Response(
                200,
                json={
                    "status": "REVIEW_REQUIRED",
                    "completed_chunks": 0,
                    "total_chunks": 12,
                    "last_error": "quota_exceeded: 86 credits remain",
                },
                request=request,
            )
        raise AssertionError(f"unexpected url {url}")

    mock_get.side_effect = handler

    report = run_pipeline_audit(settings=_settings(), output_dir=tmp_path)
    assert report.overall == CheckStatus.FAIL
    names = [c.name for c in report.checks]
    assert "Cloud API" in names
    assert "ElevenLabs credits" in names
    assert "Audio job (Agent 3)" in names
    audio_check = next(c for c in report.checks if c.name == "Audio job (Agent 3)")
    assert audio_check.status == CheckStatus.FAIL
    assert "quota" in audio_check.detail.lower()
