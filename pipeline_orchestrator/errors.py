"""Structured pipeline failures with agent attribution and fix hints."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

AgentName = Literal["compose", "enhance", "tts", "download"]

AGENT_LABELS: dict[AgentName, str] = {
    "compose": "Agent 1 (Pattern Transcript Composer)",
    "enhance": "Agent 2 (ElevenLabs Script Doctor)",
    "tts": "Agent 3 (TTS audio worker)",
    "download": "Download (final MP3)",
}

_QUOTA_PATTERN = re.compile(r"quota|credits?\s+remain|insufficient", re.IGNORECASE)
_TRANSIENT_HTTP_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_TRANSIENT_MESSAGE_PATTERN = re.compile(
    r"service unavailable|timed?\s*out|timeout|connection (?:reset|refused|error)|"
    r"network error|temporarily unavailable|rate limit|too many requests|"
    r"bad gateway|gateway timeout|internal server error|cloudwatch|lambda",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PipelineFailure:
    agent: AgentName
    message: str
    fix_hint: str
    transcript_id: str | None = None
    audio_job_id: str | None = None
    transcript_status: str | None = None
    audio_status: str | None = None

    def format_report(self) -> str:
        lines = [
            "",
            "=== PIPELINE STOPPED ===",
            "",
            f"Agent:  {AGENT_LABELS[self.agent]}",
            f"Error:  {self.message}",
            "",
            "What to do:",
        ]
        for hint_line in self.fix_hint.strip().splitlines():
            lines.append(f"  {hint_line.strip()}")
        lines.append("")
        lines.append("IDs (re-run the same command to resume from this point):")
        lines.append(f"  transcript_id: {self.transcript_id or '(none yet)'}")
        lines.append(f"  audio_job_id:  {self.audio_job_id or '(none yet)'}")
        if self.transcript_status:
            lines.append(f"  transcript status: {self.transcript_status}")
        if self.audio_status:
            lines.append(f"  audio job status:  {self.audio_status}")
        lines.append("")
        lines.append("Full health audit (share with non-technical reviewers):")
        lines.append("  .\\scripts\\audit.ps1 -SaveReport")
        lines.append("  See guide/operator-audit.md")
        lines.append("")
        return "\n".join(lines)


def is_quota_error(message: str | None) -> bool:
    if not message or not isinstance(message, str):
        return False
    return bool(_QUOTA_PATTERN.search(message))


def is_transient_third_party_error(
    message: str | None,
    *,
    status_code: int | None = None,
) -> bool:
    """True for AWS/API Gateway/Lambda/ElevenLabs outages worth retrying."""
    if is_quota_error(message):
        return False
    if status_code is not None and status_code in _TRANSIENT_HTTP_STATUS_CODES:
        return True
    if not message:
        return False
    return bool(_TRANSIENT_MESSAGE_PATTERN.search(message))


def retry_limit_for_error(
    base_limit: int,
    *,
    third_party_extra: int,
    message: str | None,
    status_code: int | None = None,
) -> int:
    """Allow extra graph-level attempts when a third-party dependency is flaky."""
    if is_transient_third_party_error(message, status_code=status_code):
        return base_limit + third_party_extra
    return base_limit


def build_failure(
    agent: AgentName,
    message: str,
    *,
    transcript_id: str | None = None,
    audio_job_id: str | None = None,
    transcript_status: str | None = None,
    audio_status: str | None = None,
    last_error: str | None = None,
) -> PipelineFailure:
    detail = message
    if last_error and last_error not in message:
        detail = f"{message} — {last_error}"

    fix_hint = _fix_hint_for(agent, detail, transcript_status, audio_status)
    return PipelineFailure(
        agent=agent,
        message=detail,
        fix_hint=fix_hint,
        transcript_id=transcript_id,
        audio_job_id=audio_job_id,
        transcript_status=transcript_status,
        audio_status=audio_status,
    )


def _fix_hint_for(
    agent: AgentName,
    message: str,
    transcript_status: str | None,
    audio_status: str | None,
) -> str:
    if is_quota_error(message):
        return (
            "- Top up ElevenLabs credits at https://elevenlabs.io\n"
            "- Re-run: python -m pipeline_orchestrator (resumes TTS only; compose/enhance are kept)"
        )

    if agent == "compose":
        return (
            "- Transient AWS/API errors are retried automatically (up to 3 extra attempts)\n"
            "- Check API key and network connectivity to the intake API\n"
            "- Verify brief fields (generation, wound, pillar) are valid\n"
            "- Re-run the same command to retry Agent 1"
        )

    if agent == "enhance":
        if transcript_status == "REVIEW_REQUIRED":
            return (
                "- Agent 2 flagged the transcript for human review\n"
                "- Inspect transcript content via GET /transcripts/{id}/versions\n"
                "- Re-run the same command to retry enhancement after fixes"
            )
        return (
            "- Check CloudWatch: /aws/lambda/creative-agent-dev-enhancer\n"
            "- Re-run the same command to retry Agent 2 only (raw transcript is preserved)"
        )

    if agent == "tts":
        if is_quota_error(message):
            return (
                "- ElevenLabs credits exhausted (free tier: 10,000 chars/month)\n"
                "- Top up at https://elevenlabs.io or wait for monthly reset\n"
                "- After topping up, replay TTS:\n"
                "    python scripts/run_tts_workflow_smoke.py --audio-job-id <id> --start-at LoadEnhancedTranscript\n"
                "- Then: python -m pipeline_orchestrator (resumes download only)"
            )
        if audio_status == "REVIEW_REQUIRED":
            return (
                "- TTS stopped before all chunks were synthesized\n"
                "- If the error mentions quota/credits, top up at https://elevenlabs.io first\n"
                "- Replay TTS for this audio job:\n"
                "    python scripts/run_tts_workflow_smoke.py --audio-job-id <id> --start-at LoadEnhancedTranscript\n"
                "- Then: python -m pipeline_orchestrator (resumes download only)\n"
                "- Full health check: .\\scripts\\audit.ps1 -SaveReport"
            )
        return (
            "- Check CloudWatch: /aws/lambda/creative-agent-dev-tts-worker\n"
            "- Re-run the same command to retry TTS only"
        )

    return (
        "- Check that the audio job manifest has a final_url\n"
        "- Re-run the same command to retry download"
    )
