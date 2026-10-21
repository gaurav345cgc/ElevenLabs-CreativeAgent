"""Plain-language pipeline health audit for operators and non-technical reviewers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from pipeline_orchestrator.checkpoint import PipelineCheckpoint, checkpoint_path, load_checkpoint
from pipeline_orchestrator.config import OrchestratorSettings, resolve_api_key
from pipeline_orchestrator.errors import (
    AGENT_LABELS,
    AgentName,
    build_failure,
    is_quota_error,
    is_transient_third_party_error,
)

# Typical full meditation from recent production runs (~5 min target, ~6.4 min audio).
TYPICAL_MEDITATION_CREDITS = 4_700


class CheckStatus(StrEnum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True)
class AuditCheck:
    name: str
    status: CheckStatus
    summary: str
    detail: str = ""
    action: str = ""


@dataclass(frozen=True)
class PipelineAuditReport:
    generated_at: datetime
    overall: CheckStatus
    headline: str
    checks: tuple[AuditCheck, ...]
    transcript_id: str | None = None
    audio_job_id: str | None = None
    local_mp3_path: str | None = None

    def format_text(self) -> str:
        width = 52
        lines = [
            "",
            "CREATIVE AGENT — PIPELINE AUDIT",
            f"Generated: {self.generated_at.astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
            "",
            f"OVERALL: {self.overall.value} — {self.headline}",
            "",
            "Checks",
            "-" * width,
        ]
        for check in self.checks:
            label = f"{check.name:<28} [{check.status.value}]"
            lines.append(label)
            lines.append(f"  {check.summary}")
            if check.detail:
                lines.append(f"  Detail: {check.detail}")
            if check.action:
                lines.append(f"  Action: {check.action}")
            lines.append("")

        actions = [c.action for c in self.checks if c.action and c.status != CheckStatus.OK]
        if actions:
            lines.append("What to do next")
            lines.append("-" * width)
            for idx, action in enumerate(actions, start=1):
                lines.append(f"{idx}. {action}")
            lines.append("")

        if self.transcript_id or self.audio_job_id:
            lines.append("Saved IDs")
            lines.append("-" * width)
            lines.append(f"  transcript_id: {self.transcript_id or '(none)'}")
            lines.append(f"  audio_job_id:  {self.audio_job_id or '(none)'}")
            if self.local_mp3_path:
                lines.append(f"  final mp3:     {self.local_mp3_path}")
            lines.append("")

        lines.append("To re-run this audit: .\\scripts\\audit.ps1")
        lines.append("To resume the pipeline: .\\scripts\\run.ps1")
        lines.append("")
        return "\n".join(lines)


def run_pipeline_audit(
    *,
    settings: OrchestratorSettings | None = None,
    output_dir: Path | None = None,
) -> PipelineAuditReport:
    settings = settings or OrchestratorSettings.from_env()
    out = output_dir or settings.output_dir
    checkpoint = load_checkpoint(out)
    checks: list[AuditCheck] = []

    checks.append(_check_api_health(settings))
    checks.append(_check_elevenlabs_credits())
    checks.append(_check_checkpoint(out, checkpoint))
    checks.extend(_check_saved_jobs(settings, checkpoint))

    overall, headline = _overall_status(checks)
    return PipelineAuditReport(
        generated_at=datetime.now(UTC),
        overall=overall,
        headline=headline,
        checks=tuple(checks),
        transcript_id=checkpoint.transcript_id if checkpoint else None,
        audio_job_id=checkpoint.audio_job_id if checkpoint else None,
        local_mp3_path=checkpoint.local_mp3_path if checkpoint else None,
    )


def _headers(settings: OrchestratorSettings) -> dict[str, str]:
    return {
        "X-API-Key": settings.api_key,
        "X-Tenant-Id": str(settings.tenant_id),
    }


def _check_api_health(settings: OrchestratorSettings) -> AuditCheck:
    url = f"{settings.api_base_url}/health?deep=true"
    try:
        response = httpx.get(url, headers=_headers(settings), timeout=20.0)
        if response.status_code >= 500:
            return AuditCheck(
                name="Cloud API",
                status=CheckStatus.FAIL,
                summary=f"API returned error {response.status_code}",
                detail=response.text[:200],
                action="Wait a few minutes and run the audit again. If it persists, contact engineering.",
            )
        payload = response.json()
        checks = payload.get("checks", {})
        db_ok = checks.get("db", {}).get("ok", True)
        if not db_ok:
            return AuditCheck(
                name="Cloud API",
                status=CheckStatus.FAIL,
                summary="API is up but the database check failed",
                detail=str(checks.get("db", {}).get("error", "")),
                action="Contact engineering — AWS database may be unavailable.",
            )
        return AuditCheck(
            name="Cloud API",
            status=CheckStatus.OK,
            summary="API and database are reachable",
        )
    except httpx.HTTPError as exc:
        return AuditCheck(
            name="Cloud API",
            status=CheckStatus.FAIL,
            summary="Cannot reach the Creative Agent API",
            detail=str(exc),
            action="Check internet connection, VPN, and API URL in .env",
        )


def _check_elevenlabs_credits() -> AuditCheck:
    try:
        from tts_pipeline.generator.elevenlabs_client import ElevenLabsClient

        subscription = ElevenLabsClient.from_env().get_subscription()
        remaining = subscription.credits_remaining
        limit = subscription.character_limit
        tier = subscription.tier or "unknown"
        if remaining < TYPICAL_MEDITATION_CREDITS:
            runs_left = max(remaining // TYPICAL_MEDITATION_CREDITS, 0)
            return AuditCheck(
                name="ElevenLabs credits",
                status=CheckStatus.FAIL,
                summary=f"Not enough credits for a full meditation ({remaining:,} left)",
                detail=(
                    f"Typical run needs ~{TYPICAL_MEDITATION_CREDITS:,} credits. "
                    f"Monthly limit {limit:,} ({tier} tier)."
                ),
                action="Top up at https://elevenlabs.io or wait for the monthly reset.",
            )
        if remaining < TYPICAL_MEDITATION_CREDITS * 2:
            return AuditCheck(
                name="ElevenLabs credits",
                status=CheckStatus.WARN,
                summary=f"Low credits — about one full run left ({remaining:,})",
                detail=f"Monthly limit {limit:,} ({tier} tier).",
                action="Plan a credit top-up before the next production batch.",
            )
        return AuditCheck(
            name="ElevenLabs credits",
            status=CheckStatus.OK,
            summary=f"{remaining:,} credits available ({tier} tier)",
            detail=f"Enough for roughly {remaining // TYPICAL_MEDITATION_CREDITS} full meditations.",
        )
    except Exception as exc:
        return AuditCheck(
            name="ElevenLabs credits",
            status=CheckStatus.WARN,
            summary="Could not read ElevenLabs balance",
            detail=str(exc),
            action="Check CREATIVE_AGENT_ELEVENLABS_API_KEY in .env",
        )


def _check_checkpoint(output_dir: Path, checkpoint: PipelineCheckpoint | None) -> AuditCheck:
    path = checkpoint_path(output_dir)
    if checkpoint is None:
        return AuditCheck(
            name="Last pipeline run",
            status=CheckStatus.OK,
            summary="No saved run in progress (ready for a new meditation)",
        )
    stage = checkpoint.stage or "unknown"
    if stage == "done":
        mp3 = checkpoint.local_mp3_path
        if mp3 and Path(mp3).is_file():
            return AuditCheck(
                name="Last pipeline run",
                status=CheckStatus.OK,
                summary="Last run completed successfully",
                detail=f"MP3: {mp3}",
            )
        return AuditCheck(
            name="Last pipeline run",
            status=CheckStatus.WARN,
            summary="Marked done but MP3 file is missing locally",
            action="Run .\\scripts\\run.ps1 to download again.",
        )
    if stage == "failed":
        return AuditCheck(
            name="Last pipeline run",
            status=CheckStatus.FAIL,
            summary="Last run stopped with an error",
            detail=f"Checkpoint saved at {path.name}",
            action="Read the job checks below, fix the issue, then run .\\scripts\\run.ps1 to resume.",
        )
    return AuditCheck(
        name="Last pipeline run",
        status=CheckStatus.WARN,
        summary=f"Run in progress or interrupted (stage: {stage})",
        detail=f"Checkpoint saved at {path.name}",
        action="Run .\\scripts\\run.ps1 to resume where it left off.",
    )


def _check_saved_jobs(
    settings: OrchestratorSettings,
    checkpoint: PipelineCheckpoint | None,
) -> list[AuditCheck]:
    if checkpoint is None:
        return []
    results: list[AuditCheck] = []
    if checkpoint.transcript_id:
        results.append(_check_transcript(settings, checkpoint.transcript_id))
    if checkpoint.audio_job_id:
        results.append(_check_audio_job(settings, checkpoint.audio_job_id))
    if checkpoint.local_mp3_path:
        results.append(_check_local_mp3(checkpoint.local_mp3_path))
    return results


def _check_transcript(settings: OrchestratorSettings, transcript_id: str) -> AuditCheck:
    try:
        response = httpx.get(
            f"{settings.api_base_url}/transcripts/{transcript_id}",
            headers=_headers(settings),
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status", "unknown")
        last_error = payload.get("last_error") or ""
        if status == "ENHANCED":
            return AuditCheck(
                name="Transcript (Agent 1+2)",
                status=CheckStatus.OK,
                summary="Transcript is ready for audio (ENHANCED)",
                detail=f"transcript_id={transcript_id}",
            )
        if status in {"PENDING_ENHANCEMENT", "ENHANCING"}:
            return AuditCheck(
                name="Transcript (Agent 1+2)",
                status=CheckStatus.WARN,
                summary=f"Still processing enhancement ({status})",
                action="Run .\\scripts\\run.ps1 and wait — Agent 2 is still working.",
            )
        if status in {"FAILED_ENHANCEMENT", "REVIEW_REQUIRED"}:
            return AuditCheck(
                name="Transcript (Agent 1+2)",
                status=CheckStatus.FAIL,
                summary=f"Enhancement needs attention ({status})",
                detail=last_error[:240] if last_error else "",
                action="Contact engineering or retry with .\\scripts\\run.ps1",
            )
        return AuditCheck(
            name="Transcript (Agent 1+2)",
            status=CheckStatus.WARN,
            summary=f"Unexpected status: {status}",
            detail=last_error[:240] if last_error else "",
        )
    except httpx.HTTPError as exc:
        return AuditCheck(
            name="Transcript (Agent 1+2)",
            status=CheckStatus.WARN,
            summary="Could not load transcript status",
            detail=str(exc),
        )


def _check_audio_job(settings: OrchestratorSettings, audio_job_id: str) -> AuditCheck:
    last_error = ""
    status = "unknown"
    chunks = ""
    try:
        response = httpx.get(
            f"{settings.api_base_url}/audio-jobs/{audio_job_id}",
            headers=_headers(settings),
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status", "unknown")
        last_error = payload.get("last_error") or ""
        completed = payload.get("completed_chunks", 0)
        total = payload.get("total_chunks")
        chunks = f"{completed}/{total or '?'}"
    except httpx.HTTPError:
        pass

    if not last_error:
        last_error = _audio_job_last_error_from_db(UUID(audio_job_id)) or ""

    if status == "COMPLETED":
        return AuditCheck(
            name="Audio job (Agent 3)",
            status=CheckStatus.OK,
            summary="Audio synthesis finished (COMPLETED)",
            detail=f"audio_job_id={audio_job_id} chunks {chunks}",
            action="Run .\\scripts\\run.ps1 to download the MP3 if you do not have it yet.",
        )
    if status in {"CREATED", "PLANNING", "READY", "GENERATING"}:
        return AuditCheck(
            name="Audio job (Agent 3)",
            status=CheckStatus.WARN,
            summary=f"Audio is still being produced ({status})",
            detail=f"chunks {chunks}",
            action="Wait and run .\\scripts\\run.ps1 to continue waiting.",
        )
    if is_quota_error(last_error):
        return AuditCheck(
            name="Audio job (Agent 3)",
            status=CheckStatus.FAIL,
            summary="Stopped — ElevenLabs credits exhausted",
            detail=last_error[:280],
            action=(
                "Top up ElevenLabs credits, then ask engineering to replay TTS "
                "or run: python scripts/run_tts_workflow_smoke.py --audio-job-id "
                f"{audio_job_id} --start-at LoadEnhancedTranscript"
            ),
        )
    if status == "REVIEW_REQUIRED":
        return AuditCheck(
            name="Audio job (Agent 3)",
            status=CheckStatus.FAIL,
            summary="Audio job needs review before it can continue",
            detail=(last_error or f"status REVIEW_REQUIRED, chunks {chunks}")[:280],
            action="Share this audit with engineering. Check CloudWatch: creative-agent-dev-tts-worker",
        )
    if status in {"FAILED", "PARTIALLY_FAILED"}:
        return AuditCheck(
            name="Audio job (Agent 3)",
            status=CheckStatus.FAIL,
            summary=f"Audio synthesis failed ({status})",
            detail=last_error[:280] if last_error else f"chunks {chunks}",
            action="Run .\\scripts\\run.ps1 to retry TTS after the issue is fixed.",
        )
    return AuditCheck(
        name="Audio job (Agent 3)",
        status=CheckStatus.WARN,
        summary=f"Status: {status}",
        detail=last_error[:280] if last_error else f"chunks {chunks}",
    )


from pipeline_orchestrator.client import _audio_job_last_error_from_db


def _check_local_mp3(path_str: str) -> AuditCheck:
    path = Path(path_str)
    if path.is_file():
        size_mb = path.stat().st_size / (1024 * 1024)
        return AuditCheck(
            name="Final MP3 on disk",
            status=CheckStatus.OK,
            summary=f"Found {path.name} ({size_mb:.1f} MB)",
            detail=str(path.resolve()),
        )
    return AuditCheck(
        name="Final MP3 on disk",
        status=CheckStatus.WARN,
        summary="MP3 path recorded but file is missing",
        detail=path_str,
        action="Run .\\scripts\\run.ps1 to download again.",
    )


def _overall_status(checks: list[AuditCheck]) -> tuple[CheckStatus, str]:
    if any(c.status == CheckStatus.FAIL for c in checks):
        failed = next(c for c in checks if c.status == CheckStatus.FAIL)
        return CheckStatus.FAIL, failed.summary
    if any(c.status == CheckStatus.WARN for c in checks):
        warned = next(c for c in checks if c.status == CheckStatus.WARN)
        return CheckStatus.WARN, warned.summary
    return CheckStatus.OK, "All checks passed — system looks healthy"


def diagnose_checkpoint_failure(
    checkpoint: PipelineCheckpoint | None,
    *,
    last_error: str | None = None,
) -> str:
    """Build operator guidance from a failed checkpoint without running HTTP checks."""
    if checkpoint is None:
        return "No checkpoint found. Run .\\scripts\\audit.ps1 for a full health check."

    agent: AgentName = "compose"
    if checkpoint.audio_job_id:
        agent = "tts"
    elif checkpoint.transcript_id:
        agent = "enhance" if checkpoint.stage == "enhance" else "tts"

    failure = build_failure(
        agent,
        last_error or "Pipeline stopped",
        transcript_id=checkpoint.transcript_id,
        audio_job_id=checkpoint.audio_job_id,
        audio_status="REVIEW_REQUIRED" if agent == "tts" else None,
        last_error=last_error,
    )
    return failure.format_report()
