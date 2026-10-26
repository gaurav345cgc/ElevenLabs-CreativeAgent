"""Agentic end-to-end loop: Orchestrator Brain decides, tools execute."""

from __future__ import annotations

import logging
from typing import Any

from observability.logging import log_orchestrator_event
from pipeline_orchestrator.brain import BrainDecision, OrchestratorBrain
from pipeline_orchestrator.checkpoint import save_checkpoint
from pipeline_orchestrator.client import CreativeAgentClient
from pipeline_orchestrator.config import OrchestratorSettings
from pipeline_orchestrator.nodes import (
    run_compose,
    run_download,
    run_enhance,
    run_qa_repair,
    run_tts,
)
from pipeline_orchestrator.resume import resolve_resume_cursor
from pipeline_orchestrator.run_lock import update_run_lock
from pipeline_orchestrator.state import PipelineState

logger = logging.getLogger("creative_agent.orchestrator.agentic")


def _append_decision(state: PipelineState, decision: BrainDecision, **extra: Any) -> list[dict[str, Any]]:
    entry = {
        "action": decision.action,
        "reason": decision.reason,
        "thought": (decision.thought or "")[:300],
        **extra,
    }
    return [*(state.get("decision_log") or []), entry]


def execute_decision(
    state: PipelineState,
    decision: BrainDecision,
    *,
    client: CreativeAgentClient,
    settings: OrchestratorSettings,
    compose_brief: dict[str, Any],
) -> PipelineState:
    """Run one brain action against existing pipeline tools."""
    action = decision.action
    brief = dict(state.get("compose_brief") or compose_brief)

    if action == "complete":
        return {
            **state,
            "compose_brief": brief,
            "stage": "done",
            "decision_log": _append_decision(state, decision),
            "log": [f"brain: complete — {decision.reason}"],
        }

    if action == "fail":
        message = (decision.fail_message or decision.reason or "orchestrator failed").strip()
        return {
            **state,
            "compose_brief": brief,
            "stage": "failed",
            "failed_agent": state.get("failed_agent") or "compose",
            "last_error": message,
            "fix_hint": decision.reason or message,
            "decision_log": _append_decision(state, decision),
            "log": [f"brain: fail — {message}"],
        }

    if action == "compose":
        next_state = run_compose(
            {**state, "compose_brief": brief, "stage": "compose"},
            client=client,
            settings=settings,
            compose_brief=brief,
        )
        next_state = {
            **next_state,
            "decision_log": _append_decision(state, decision),
            "brain_steps": int(state.get("brain_steps") or 0) + 1,
        }
        return next_state

    if action == "repair_and_compose":
        # Apply repair (may set stage=compose or failed), then immediately compose once
        # if repair succeeded — brain asked for repair_and_compose as one unit.
        repaired = run_qa_repair(
            {**state, "compose_brief": brief},
            settings=settings,
            extra_instructions=decision.composer_instructions or None,
        )
        repaired = {
            **repaired,
            "decision_log": _append_decision(state, decision),
            "brain_steps": int(state.get("brain_steps") or 0) + 1,
        }
        if repaired.get("stage") == "failed":
            return repaired
        # stage should be compose — run Agent 1 with new repair_context
        composed = run_compose(
            repaired,
            client=client,
            settings=settings,
            compose_brief=repaired.get("compose_brief") or brief,
        )
        composed["decision_log"] = repaired.get("decision_log") or _append_decision(state, decision)
        composed["brain_steps"] = repaired.get("brain_steps")
        return composed

    if action == "enhance":
        next_state = run_enhance(
            {**state, "compose_brief": brief, "stage": "enhance"},
            client=client,
            settings=settings,
        )
        return {
            **next_state,
            "decision_log": _append_decision(state, decision),
            "brain_steps": int(state.get("brain_steps") or 0) + 1,
        }

    if action == "tts":
        next_state = run_tts(
            {**state, "compose_brief": brief, "stage": "tts"},
            client=client,
            settings=settings,
        )
        return {
            **next_state,
            "decision_log": _append_decision(state, decision),
            "brain_steps": int(state.get("brain_steps") or 0) + 1,
        }

    if action == "download":
        next_state = run_download(
            {**state, "compose_brief": brief, "stage": "download"},
            client=client,
            settings=settings,
        )
        # run_download sets done on success
        return {
            **next_state,
            "decision_log": _append_decision(state, decision),
            "brain_steps": int(state.get("brain_steps") or 0) + 1,
        }

    return {
        **state,
        "stage": "failed",
        "failed_agent": "compose",
        "last_error": f"unknown brain action {action!r}",
        "decision_log": _append_decision(state, decision),
        "log": [f"brain: unknown action {action}"],
    }


def run_agentic_pipeline(
    state_in: PipelineState,
    *,
    client: CreativeAgentClient,
    settings: OrchestratorSettings,
    compose_brief: dict[str, Any],
    brain: OrchestratorBrain | None = None,
    max_steps: int | None = None,
) -> PipelineState:
    """Brain loop until done/failed or step budget exhausted."""
    step_limit = max_steps if max_steps is not None else settings.max_brain_steps
    judge = brain or OrchestratorBrain(max_repairs=settings.max_compose_repair_attempts)
    state: PipelineState = {
        **state_in,
        "compose_brief": state_in.get("compose_brief") or compose_brief,
        "decision_log": list(state_in.get("decision_log") or []),
        "brain_steps": int(state_in.get("brain_steps") or 0),
    }

    # Intelligent resume: ask live API where this job actually is.
    if state.get("stage") in {None, "route"} or state.get("transcript_id") or state.get(
        "audio_job_id"
    ):
        state = resolve_resume_cursor(state, client=client)
        log_orchestrator_event(
            f"resume cursor → {state.get('stage')}",
            event_type="resume_cursor",
            stage=state.get("stage"),
            transcript_id=state.get("transcript_id"),
            audio_job_id=state.get("audio_job_id"),
            transcript_status=state.get("last_transcript_status"),
            audio_status=state.get("last_audio_status"),
            correlation_id=state.get("correlation_id"),
        )
        save_checkpoint(settings.output_dir, state)

    for step in range(step_limit):
        if state.get("stage") in {"done", "failed"}:
            break

        decision = judge.decide(dict(state))
        log_orchestrator_event(
            f"brain step {step + 1}: {decision.action}",
            event_type="brain_decision",
            action=decision.action,
            reason=decision.reason,
            correlation_id=state.get("correlation_id"),
            transcript_id=state.get("transcript_id"),
            thought=(decision.thought or "")[:200],
        )

        prev_stage = state.get("stage")
        state = execute_decision(
            state,
            decision,
            client=client,
            settings=settings,
            compose_brief=compose_brief,
        )
        save_checkpoint(settings.output_dir, state)
        update_run_lock(
            settings.output_dir,
            correlation_id=state.get("correlation_id"),
            transcript_id=state.get("transcript_id"),
            audio_job_id=state.get("audio_job_id"),
        )

        # Avoid tight loops: same fail-less no-op
        if (
            state.get("stage") == prev_stage
            and decision.action in {"enhance", "tts"}
            and state.get("stage") not in {"done", "failed"}
        ):
            # enhance/tts may intentionally re-enter same stage while polling;
            # count toward brain_steps already. Continue.
            pass

        if state.get("stage") in {"done", "failed"}:
            break
    else:
        # step budget exhausted
        if state.get("stage") not in {"done", "failed"}:
            state = {
                **state,
                "stage": "failed",
                "failed_agent": state.get("failed_agent") or "compose",
                "last_error": f"orchestrator brain exceeded max_steps={step_limit}",
                "fix_hint": "Inspect decision_log and resume with --transcript-id / --audio-job-id",
                "log": [f"brain: max_steps={step_limit} exhausted"],
            }
            save_checkpoint(settings.output_dir, state)

    return state


def resolve_orchestrator_mode(override: str | None = None) -> str:
    """agentic | graph | auto — auto uses agentic when OpenAI key is present."""
    import os

    from transcript_composer.llm_config import ensure_dotenv_loaded, resolve_openai_api_key

    ensure_dotenv_loaded()
    mode = (override or os.environ.get("CREATIVE_AGENT_ORCHESTRATOR", "auto")).strip().lower()
    if mode in {"agentic", "graph"}:
        return mode
    # auto
    return "agentic" if resolve_openai_api_key() else "graph"
