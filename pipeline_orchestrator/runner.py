"""CLI and programmatic entry for the LangGraph pipeline orchestrator."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import UUID

from pipeline_orchestrator.checkpoint import (
    clear_checkpoint,
    is_run_finished,
    is_run_resumable,
    load_checkpoint,
    save_checkpoint,
    state_from_checkpoint,
)
from observability.logging import configure_orchestrator_logging, log_orchestrator_event
from pipeline_orchestrator.client import CreativeAgentClient
from pipeline_orchestrator.config import DEFAULT_TENANT_ID, OrchestratorSettings
from pipeline_orchestrator.errors import AgentName, PipelineFailure, build_failure
from pipeline_orchestrator.graph import build_pipeline_graph
from pipeline_orchestrator.state import PipelineState, initial_state

logger = logging.getLogger("creative_agent.orchestrator")


def _print_audit_hint(settings: OrchestratorSettings) -> None:
    try:
        from observability.pipeline_audit import run_pipeline_audit

        report = run_pipeline_audit(settings=settings, output_dir=settings.output_dir)
        print(report.format_text(), file=sys.stderr)
    except Exception as exc:
        logger.warning("audit after failure skipped: %s", exc)


@dataclass(frozen=True)
class PipelineRunConfig:
    tenant_id: UUID = DEFAULT_TENANT_ID
    api_key: str | None = None
    api_base_url: str | None = None
    correlation_id: str | None = None
    transcript_id: str | None = None
    audio_job_id: str | None = None
    duration_minutes: int = 5
    voice_profile_code: str = "drew_primary"
    output_dir: Path | None = None
    poll_seconds: float = 15.0
    enhancement_timeout_minutes: int = 15
    tts_timeout_minutes: int = 25
    max_compose_retries: int = 2
    max_enhance_retries: int = 3
    max_tts_retries: int = 3
    accept_partial_tts: bool = False
    skip_tts: bool = False
    fresh: bool = False
    generation_code: str = "millennial"
    wound_id: str = "ml_02"
    stage_no: int = 2
    pillar_code: str = "p04"
    content_type: str = "guided_meditation"


def _settings_from_config(config: PipelineRunConfig) -> OrchestratorSettings:
    base = OrchestratorSettings.from_env(
        api_key=config.api_key,
        api_base_url=config.api_base_url,
        tenant_id=config.tenant_id,
    )
    updates: dict[str, Any] = {
        "poll_seconds": config.poll_seconds,
        "enhancement_timeout_seconds": config.enhancement_timeout_minutes * 60,
        "tts_timeout_seconds": config.tts_timeout_minutes * 60,
        "max_compose_retries": config.max_compose_retries,
        "max_enhance_retries": config.max_enhance_retries,
        "max_tts_retries": config.max_tts_retries,
        "voice_profile_code": config.voice_profile_code,
        "accept_partial_tts": config.accept_partial_tts,
    }
    if config.output_dir is not None:
        updates["output_dir"] = config.output_dir
    return replace(base, **updates)


def _compose_brief(config: PipelineRunConfig, tenant_id: UUID) -> dict[str, Any]:
    return {
        "tenant_id": str(tenant_id),
        "content_type": config.content_type,
        "generation_code": config.generation_code,
        "wound_id": config.wound_id,
        "stage_no": config.stage_no,
        "target_duration_minutes": config.duration_minutes,
        "pillar_code": config.pillar_code,
    }


def _resolve_initial_state(
    config: PipelineRunConfig,
    settings: OrchestratorSettings,
    client: CreativeAgentClient,
) -> tuple[PipelineState, str]:
    """Return graph input state and a human-readable mode label."""
    if config.transcript_id or config.audio_job_id:
        return (
            initial_state(
                transcript_id=config.transcript_id,
                audio_job_id=config.audio_job_id,
                skip_compose=bool(config.transcript_id),
                skip_tts=config.skip_tts,
                correlation_id=config.correlation_id or str(uuid.uuid4()),
            ),
            "explicit IDs",
        )

    if not config.fresh:
        checkpoint = load_checkpoint(settings.output_dir)
        if checkpoint is not None:
            if is_run_finished(client, checkpoint):
                clear_checkpoint(settings.output_dir)
                log_orchestrator_event(
                    "previous run completed; starting new pipeline",
                    event_type="run_start",
                    mode="new_after_complete",
                )
            elif is_run_resumable(client, checkpoint):
                log_orchestrator_event(
                    "resuming incomplete pipeline from checkpoint",
                    event_type="run_resume",
                    transcript_id=checkpoint.transcript_id,
                    audio_job_id=checkpoint.audio_job_id,
                    correlation_id=checkpoint.correlation_id,
                )
                return state_from_checkpoint(checkpoint), "checkpoint resume"

    return (
        initial_state(
            correlation_id=config.correlation_id or str(uuid.uuid4()),
            skip_tts=config.skip_tts,
        ),
        "new run",
    )


def _failure_from_state(state: PipelineState) -> PipelineFailure:
    agent: AgentName = state.get("failed_agent") or "compose"  # type: ignore[assignment]
    return build_failure(
        agent,
        state.get("last_error") or "pipeline failed",
        transcript_id=state.get("transcript_id"),
        audio_job_id=state.get("audio_job_id"),
        transcript_status=state.get("last_transcript_status"),
        audio_status=state.get("last_audio_status"),
    )


def run_pipeline(config: PipelineRunConfig) -> PipelineState:
    configure_orchestrator_logging()
    settings = _settings_from_config(config)
    client = CreativeAgentClient(settings)
    graph = build_pipeline_graph(
        client=client,
        settings=settings,
        compose_brief=_compose_brief(config, settings.tenant_id),
    )

    state_in, mode = _resolve_initial_state(config, settings, client)
    log_orchestrator_event(
        "pipeline run started",
        event_type="run_start",
        mode=mode,
        api_base_url=settings.api_base_url,
        output_dir=str(settings.output_dir),
        correlation_id=state_in.get("correlation_id"),
    )

    final: PipelineState = state_in
    for event in graph.stream(state_in):
        for _node_name, node_state in event.items():
            save_checkpoint(settings.output_dir, node_state)
            final = node_state

    if final.get("stage") == "done":
        clear_checkpoint(settings.output_dir)
        log_orchestrator_event(
            "pipeline run completed",
            event_type="run_complete",
            transcript_id=final.get("transcript_id"),
            audio_job_id=final.get("audio_job_id"),
            local_mp3_path=final.get("local_mp3_path"),
            correlation_id=final.get("correlation_id"),
        )

    if final.get("stage") == "failed":
        failure = _failure_from_state(final)
        log_orchestrator_event(
            failure.message,
            level=logging.ERROR,
            event_type="run_failed",
            failed_agent=final.get("failed_agent"),
            fix_hint=final.get("fix_hint"),
            transcript_id=final.get("transcript_id"),
            audio_job_id=final.get("audio_job_id"),
            correlation_id=final.get("correlation_id"),
        )
        print(failure.format_report(), file=sys.stderr)
        _print_audit_hint(settings)
        raise RuntimeError(failure.message)

    return final


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "One command: create a new meditation audio job end-to-end, "
            "or resume the last incomplete run automatically."
        ),
    )
    parser.add_argument("--tenant-id", default=str(DEFAULT_TENANT_ID))
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--correlation-id", default=None)
    parser.add_argument("--transcript-id", default=None, help="Optional: force a specific transcript")
    parser.add_argument("--audio-job-id", default=None, help="Optional: force a specific audio job")
    parser.add_argument("--fresh", action="store_true", help="Ignore saved checkpoint; start new run")
    parser.add_argument("--duration-minutes", type=int, default=5)
    parser.add_argument("--voice-profile", default="drew_primary")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    parser.add_argument("--enhancement-timeout-minutes", type=int, default=15)
    parser.add_argument("--tts-timeout-minutes", type=int, default=25)
    parser.add_argument("--max-enhance-retries", type=int, default=3)
    parser.add_argument("--max-tts-retries", type=int, default=3)
    parser.add_argument("--accept-partial", action="store_true")
    parser.add_argument("--skip-tts", action="store_true", help="Stop after ENHANCED")
    parser.add_argument("--json", action="store_true", help="Print final state as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config = PipelineRunConfig(
        tenant_id=UUID(args.tenant_id),
        api_key=args.api_key,
        api_base_url=args.api_base,
        correlation_id=args.correlation_id,
        transcript_id=args.transcript_id,
        audio_job_id=args.audio_job_id,
        fresh=args.fresh,
        duration_minutes=args.duration_minutes,
        voice_profile_code=args.voice_profile,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        poll_seconds=args.poll_seconds,
        enhancement_timeout_minutes=args.enhancement_timeout_minutes,
        tts_timeout_minutes=args.tts_timeout_minutes,
        max_enhance_retries=args.max_enhance_retries,
        max_tts_retries=args.max_tts_retries,
        accept_partial_tts=args.accept_partial,
        skip_tts=args.skip_tts,
    )

    try:
        result = run_pipeline(config)
    except RuntimeError:
        return 1
    except Exception as exc:
        settings = _settings_from_config(config)
        failure = build_failure("compose", f"unexpected orchestrator error: {exc}")
        print(failure.format_report(), file=sys.stderr)
        _print_audit_hint(settings)
        return 1

    if args.json:
        printable = {key: value for key, value in result.items() if key != "log"}
        print(json.dumps(printable, indent=2, default=str))
    else:
        log_orchestrator_event(
            "pipeline finished",
            event_type="run_summary",
            transcript_id=result.get("transcript_id"),
            audio_job_id=result.get("audio_job_id"),
            local_mp3_path=result.get("local_mp3_path"),
        )
        print("")
        print("=== PIPELINE COMPLETE ===")
        print(f"transcript_id : {result.get('transcript_id')}")
        print(f"audio_job_id  : {result.get('audio_job_id')}")
        print(f"final mp3     : {result.get('local_mp3_path')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
