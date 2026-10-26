"""LangGraph node implementations for each pipeline stage."""

from __future__ import annotations

import time
import uuid
from typing import Any
from uuid import UUID

from pipeline_orchestrator.client import CreativeAgentApiError, CreativeAgentClient
from pipeline_orchestrator.config import OrchestratorSettings
from pipeline_orchestrator.errors import (
    AgentName,
    build_failure,
    is_quota_error,
    is_transient_third_party_error,
    retry_limit_for_error,
)
from pipeline_orchestrator.logging_util import log_pipeline_error, log_pipeline_step
from pipeline_orchestrator.qa_repair import (
    build_fix_plan,
    format_qa_failure_message,
    write_qa_failure_artifact,
)
from pipeline_orchestrator.state import (
    ENHANCE_FAILURE_STATUSES,
    ENHANCE_IN_PROGRESS_STATUSES,
    ENHANCE_SUCCESS_STATUSES,
    TTS_RETRYABLE_STATUSES,
    TTS_SUCCESS_STATUS,
    PipelineState,
)


def _log(state: PipelineState, message: str, **extra: object) -> list[str]:
    return log_pipeline_step(state, message, **extra)


def _log_messages(state: PipelineState, messages: list[str]) -> list[str]:
    entries: list[str] = []
    for message in messages:
        entries.extend(_log(state, message))
    return entries


def _fail(
    state: PipelineState,
    agent: AgentName,
    message: str,
    *,
    last_error: str | None = None,
) -> PipelineState:
    failure = build_failure(
        agent,
        message,
        transcript_id=state.get("transcript_id"),
        audio_job_id=state.get("audio_job_id"),
        transcript_status=state.get("last_transcript_status"),
        audio_status=state.get("last_audio_status"),
        last_error=last_error or state.get("last_error"),
    )
    return {
        "stage": "failed",
        "failed_agent": agent,
        "last_error": failure.message,
        "fix_hint": failure.fix_hint,
        "log": log_pipeline_error(
            state,
            failure.message,
            event_type="pipeline_failed",
            failed_agent=agent,
            fix_hint=failure.fix_hint,
        ),
    }


def route_entry(
    state: PipelineState,
    *,
    client: CreativeAgentClient,
) -> PipelineState:
    """Pick the first incomplete stage instead of always restarting at compose."""
    from pipeline_orchestrator.resume import resolve_resume_cursor

    correlation_id = state.get("correlation_id") or str(uuid.uuid4())
    seeded = {**state, "correlation_id": correlation_id}
    if state.get("skip_compose") and not state.get("transcript_id") and not state.get("audio_job_id"):
        return {
            **seeded,
            **_fail(state, "compose", "no transcript_id and cannot start compose"),
            "log": _log(state, "routing pipeline entry"),
        }
    resolved = resolve_resume_cursor(seeded, client=client)
    route_notes = _log(state, "routing pipeline entry")
    resume_notes = list(resolved.get("log") or [])
    return {**resolved, "log": [*route_notes, *resume_notes]}


def _backoff_seconds(settings: OrchestratorSettings, attempt: int) -> float:
    return min(60.0, settings.third_party_retry_backoff_seconds * (attempt + 1))


def run_compose(
    state: PipelineState,
    *,
    client: CreativeAgentClient,
    settings: OrchestratorSettings,
    compose_brief: dict[str, Any],
) -> PipelineState:
    attempts = state.get("compose_attempts", 0)
    correlation_id = state.get("correlation_id")
    brief = dict(state.get("compose_brief") or compose_brief)
    try:
        created = client.compose_transcript(brief, correlation_id=correlation_id)
    except CreativeAgentApiError as exc:
        next_attempts = attempts + 1
        # Phase A: structured QA failure → qa_repair (templated fix → recompose).
        if exc.is_compose_qa_failure:
            report = exc.validation_report or {}
            return {
                **state,
                "compose_brief": brief,
                "compose_attempts": next_attempts,
                "qa_report": report,
                "stage": "qa_repair",
                "last_error": str(exc),
                "log": _log(
                    state,
                    f"compose QA failed ({report.get('error_count', '?')} errors); "
                    "routing to qa_repair",
                ),
            }

        limit = retry_limit_for_error(
            settings.max_compose_retries,
            third_party_extra=settings.max_third_party_retries,
            message=str(exc),
            status_code=exc.status_code,
        )
        exhausted = next_attempts >= limit
        transient = is_transient_third_party_error(str(exc), status_code=exc.status_code)
        if not exhausted and transient:
            time.sleep(_backoff_seconds(settings, attempts))
        if exhausted:
            return {
                **state,
                "compose_brief": brief,
                "compose_attempts": next_attempts,
                **_fail(state, "compose", "compose API call failed", last_error=str(exc)),
            }
        return {
            **state,
            "compose_brief": brief,
            "compose_attempts": next_attempts,
            "stage": "compose",
            "last_error": str(exc),
            "log": _log(
                state,
                f"compose attempt {next_attempts} failed"
                f"{' (transient; will retry)' if transient else ''}: {exc}",
            ),
        }

    transcript_id = str(created["transcript_id"])
    return {
        **state,
        "compose_brief": brief,
        "transcript_id": transcript_id,
        "compose_attempts": attempts + 1,
        "qa_report": None,
        "stage": "enhance",
        "last_transcript_status": created.get("status"),
        "log": _log(state, f"compose complete; transcript_id={transcript_id}"),
    }


def run_qa_repair(
    state: PipelineState,
    *,
    settings: OrchestratorSettings,
    extra_instructions: str | None = None,
) -> PipelineState:
    """Build templated FixPlan from qa_report and recompose with repair_context.

    ``extra_instructions`` (from Orchestrator Brain) are appended after the
    deterministic Phase A template — never replace the template floor.
    """
    report = state.get("qa_report")
    plan = build_fix_plan(report if isinstance(report, dict) else None)
    repair_attempts = int(state.get("repair_attempts") or 0)
    max_repairs = settings.max_compose_repair_attempts
    brain_extra = (extra_instructions or "").strip()
    merged_instructions = plan.composer_instructions
    if brain_extra:
        merged_instructions = (
            f"{plan.composer_instructions}\n\n"
            f"Orchestrator brain additions:\n{brain_extra}"
        )

    history = list(state.get("qa_history") or [])
    history.append(
        {
            "attempt": repair_attempts + 1,
            "summary": plan.summary,
            "root_causes": plan.root_causes,
            "error_count": (report or {}).get("error_count") if isinstance(report, dict) else None,
            "brain_extra": bool(brain_extra),
        }
    )

    if repair_attempts >= max_repairs:
        message = format_qa_failure_message(
            plan, repair_attempts=repair_attempts, max_attempts=max_repairs
        )
        artifact = write_qa_failure_artifact(
            settings.output_dir,
            correlation_id=state.get("correlation_id"),
            qa_report=report if isinstance(report, dict) else None,
            fix_plan=plan.to_dict(),
            compose_brief=state.get("compose_brief"),
        )
        failed = _fail(
            state,
            "compose",
            message,
            last_error=plan.summary,
        )
        failed["fix_hint"] = (
            f"{merged_instructions}\n\n"
            f"QA failure artifact: {artifact}"
        )
        failed["qa_history"] = history
        failed["fix_plan"] = plan.to_dict()
        return {**state, **failed}

    brief = dict(state.get("compose_brief") or {})
    brief["repair_context"] = {
        "previous_issues": [
            {
                "code": item["code"],
                "message": item.get("message") or "",
                "slot": item.get("slot"),
            }
            for item in plan.issue_payloads
        ],
        "composer_instructions": merged_instructions,
        "repair_attempt": repair_attempts + 1,
    }
    fix_dict = plan.to_dict()
    fix_dict["composer_instructions"] = merged_instructions

    return {
        **state,
        "compose_brief": brief,
        "fix_plan": fix_dict,
        "repair_attempts": repair_attempts + 1,
        "qa_history": history,
        "qa_report": None,
        "stage": "compose",
        "log": _log(
            state,
            f"qa_repair {repair_attempts + 1}/{max_repairs}: {plan.summary}"
            + (" (+brain)" if brain_extra else ""),
        ),
    }


def run_enhance(
    state: PipelineState,
    *,
    client: CreativeAgentClient,
    settings: OrchestratorSettings,
) -> PipelineState:
    transcript_id = state.get("transcript_id")
    if not transcript_id:
        return {**state, **_fail(state, "enhance", "enhance stage missing transcript_id")}

    tid = UUID(transcript_id)
    correlation_id = state.get("correlation_id")
    enhance_attempts = state.get("enhance_attempts", 0)

    tx = client.get_transcript(tid)
    status = tx.get("status")
    if status in ENHANCE_SUCCESS_STATUSES:
        return {
            **state,
            "last_transcript_status": status,
            "stage": "done" if state.get("skip_tts") else "tts",
            "log": _log(state, f"enhancement already {status}"),
        }

    if status in ENHANCE_FAILURE_STATUSES:
        last_err = tx.get("last_error")
        if is_quota_error(last_err):
            return {
                **state,
                **_fail(
                    state,
                    "enhance",
                    f"enhancement blocked ({status})",
                    last_error=last_err,
                ),
                "last_transcript_status": status,
            }
        if enhance_attempts >= retry_limit_for_error(
            settings.max_enhance_retries,
            third_party_extra=settings.max_third_party_retries,
            message=last_err,
        ):
            return {
                **state,
                **_fail(
                    state,
                    "enhance",
                    f"enhancement failed after {enhance_attempts} retries",
                    last_error=last_err,
                ),
                "last_transcript_status": status,
            }
        client.retry_enhancement(tid, correlation_id=correlation_id)
        enhance_attempts += 1
        return {
            **state,
            "enhance_attempts": enhance_attempts,
            "last_transcript_status": "PENDING_ENHANCEMENT",
            "log": _log(state, f"retry-enhancement queued (attempt {enhance_attempts})"),
        }

    deadline = time.monotonic() + settings.enhancement_timeout_seconds

    try:
        result = client.wait_for_transcript_status(
            tid,
            target_statuses=set(ENHANCE_SUCCESS_STATUSES),
            failure_statuses=ENHANCE_FAILURE_STATUSES,
            deadline=deadline,
            correlation_id=correlation_id,
        )
    except TimeoutError as exc:
        next_attempts = enhance_attempts + 1
        limit = retry_limit_for_error(
            settings.max_enhance_retries,
            third_party_extra=settings.max_third_party_retries,
            message=str(exc),
        )
        if next_attempts < limit:
            time.sleep(_backoff_seconds(settings, enhance_attempts))
            return {
                **state,
                "enhance_attempts": next_attempts,
                "last_transcript_status": status,
                "stage": "enhance",
                "last_error": str(exc),
                "log": _log(state, f"enhancement timed out (transient); retry {next_attempts}/{limit}"),
            }
        return {
            **state,
            **_fail(state, "enhance", "enhancement timed out", last_error=str(exc)),
            "last_transcript_status": status,
        }

    final_status = result.get("status")
    if final_status in ENHANCE_SUCCESS_STATUSES:
        return {
            **state,
            "last_transcript_status": final_status,
            "stage": "done" if state.get("skip_tts") else "tts",
            "log": _log(state, "enhancement complete (Agent 2)"),
        }

    if final_status in ENHANCE_FAILURE_STATUSES:
        last_err = result.get("last_error")
        if is_quota_error(last_err):
            return {
                **state,
                **_fail(
                    state,
                    "enhance",
                    f"enhancement ended with {final_status}",
                    last_error=last_err,
                ),
                "last_transcript_status": final_status,
            }
        return {
            **state,
            "last_transcript_status": final_status,
            "stage": "enhance",
            "last_error": last_err,
            "log": _log(
                state,
                f"enhancement ended with {final_status}; will retry Agent 2 only",
            ),
        }

    return {
        **state,
        **_fail(
            state,
            "enhance",
            f"unexpected transcript status after wait: {final_status}",
        ),
    }


def run_tts(
    state: PipelineState,
    *,
    client: CreativeAgentClient,
    settings: OrchestratorSettings,
) -> PipelineState:
    transcript_id = state.get("transcript_id")
    if not transcript_id:
        return {**state, **_fail(state, "tts", "tts stage missing transcript_id")}

    tid = UUID(transcript_id)
    correlation_id = state.get("correlation_id")
    attempts = state.get("tts_attempts", 0)
    audio_job_id = state.get("audio_job_id")
    last_status = state.get("last_audio_status")

    version_id = state.get("transcript_version_id")
    if not version_id:
        versions = client.list_versions(tid)
        version_list = versions.get("versions", [])
        approved = next(
            (v for v in version_list if v.get("version_kind") == "APPROVED_FINAL"),
            None,
        )
        if approved is not None:
            version_id = str(approved["version_id"])
        else:
            enhanced = next(
                (v for v in version_list if v.get("version_kind") == "ELEVENLABS_ENHANCED"),
                None,
            )
            if enhanced is None:
                return {**state, **_fail(state, "tts", "no APPROVED_FINAL or ELEVENLABS_ENHANCED version found")}
            version_id = str(enhanced["version_id"])

    should_enqueue = audio_job_id is None or bool(state.get("tts_reenqueue"))
    if should_enqueue:
        if last_status in TTS_RETRYABLE_STATUSES or state.get("tts_reenqueue"):
            last_err = None
            if audio_job_id:
                last_err = client.resolve_audio_job_last_error(
                    UUID(audio_job_id),
                    correlation_id=correlation_id,
                    cached=state.get("last_error"),
                )
            elif state.get("last_error"):
                last_err = state.get("last_error")
            if is_quota_error(last_err):
                return {
                    **state,
                    **_fail(
                        state,
                        "tts",
                        "ElevenLabs quota insufficient — top up credits before retrying TTS",
                        last_error=last_err,
                    ),
                    "last_audio_status": last_status,
                }
            if settings.accept_partial_tts and last_status == "REVIEW_REQUIRED":
                return {
                    **state,
                    "transcript_version_id": version_id,
                    "stage": "download",
                    "log": _log(state, "accepting partial TTS output (REVIEW_REQUIRED)"),
                }
            if state.get("tts_reenqueue") and attempts >= settings.max_tts_retries + settings.max_third_party_retries:
                return {
                    **state,
                    **_fail(
                        state,
                        "tts",
                        f"TTS retries exhausted after {attempts} attempts ({last_status})",
                        last_error=state.get("last_error"),
                    ),
                }

        job = client.create_audio_job(
            transcript_id=tid,
            transcript_version_id=UUID(version_id),
            correlation_id=correlation_id,
        )
        audio_job_id = str(job["audio_job_id"])
        new_status = job.get("status")
        if state.get("tts_reenqueue") and attempts > 0:
            time.sleep(_backoff_seconds(settings, attempts - 1))
        state = {
            **state,
            "transcript_version_id": version_id,
            "audio_job_id": audio_job_id,
            "tts_attempts": attempts + (1 if state.get("tts_reenqueue") else 0),
            "last_audio_status": new_status,
            "tts_reenqueue": False,
            "log": _log(
                state,
                f"audio job {'created' if job.get('created') else 're-enqueued'}: {audio_job_id}",
            ),
        }
        last_status = new_status

    if not audio_job_id:
        return {**state, **_fail(state, "tts", "tts stage missing audio_job_id")}

    if last_status in TTS_RETRYABLE_STATUSES:
        last_err = client.resolve_audio_job_last_error(
            UUID(audio_job_id),
            correlation_id=correlation_id,
            cached=state.get("last_error"),
        )
        if is_quota_error(last_err):
            return {
                **state,
                **_fail(
                    state,
                    "tts",
                    "ElevenLabs quota insufficient — top up credits before retrying TTS",
                    last_error=last_err,
                ),
                "last_audio_status": last_status,
            }

    deadline = time.monotonic() + settings.tts_timeout_seconds
    poll_logs: list[str] = []

    def _on_poll(payload: dict[str, Any]) -> None:
        chunks = f"{payload.get('completed_chunks', 0)}/{payload.get('total_chunks', '?')}"
        poll_logs.append(
            f"audio job {payload.get('status')} chunks {chunks} failed={payload.get('failed_chunks', 0)}"
        )

    try:
        result = client.wait_for_audio_job(
            UUID(audio_job_id),
            success_statuses={TTS_SUCCESS_STATUS},
            retryable_statuses=TTS_RETRYABLE_STATUSES,
            failure_statuses=set(),
            deadline=deadline,
            on_poll=_on_poll,
            correlation_id=correlation_id,
        )
    except TimeoutError as exc:
        next_attempts = attempts + 1
        limit = retry_limit_for_error(
            settings.max_tts_retries,
            third_party_extra=settings.max_third_party_retries,
            message=str(exc),
        )
        if next_attempts < limit:
            time.sleep(_backoff_seconds(settings, attempts))
            return {
                **state,
                "tts_attempts": next_attempts,
                "stage": "tts",
                "last_error": str(exc),
                "log": _log_messages(
                    state,
                    poll_logs[-3:] + [f"TTS timed out (transient); retry {next_attempts}/{limit}"],
                ),
            }
        return {
            **state,
            **_fail(state, "tts", "TTS timed out", last_error=str(exc)),
            "log": _log_messages(state, poll_logs[-3:]),
        }

    final_status = result.get("status")
    updates: PipelineState = {
        "transcript_version_id": version_id,
        "audio_job_id": audio_job_id,
        "last_audio_status": final_status,
        "log": _log_messages(state, poll_logs[-5:]),
    }

    if final_status == TTS_SUCCESS_STATUS:
        return {**state, **updates, "stage": "download"}

    if final_status in TTS_RETRYABLE_STATUSES:
        last_err = result.get("last_error")
        chunks = f"{result.get('completed_chunks', 0)}/{result.get('total_chunks', '?')}"
        summary = f"TTS ended with {final_status} ({chunks} chunks, {result.get('failed_chunks', 0)} failed)"
        if is_quota_error(last_err):
            return {
                **state,
                **updates,
                **_fail(
                    state,
                    "tts",
                    "ElevenLabs quota insufficient — top up credits before retrying TTS",
                    last_error=last_err,
                ),
            }
        if attempts >= settings.max_tts_retries + settings.max_third_party_retries:
            return {
                **state,
                **updates,
                **_fail(state, "tts", summary, last_error=last_err),
            }
        return {
            **state,
            **updates,
            "stage": "tts",
            "last_error": last_err,
            "tts_reenqueue": True,
            "log": _log(state, f"TTS {final_status}; will re-enqueue Agent 3 only"),
        }

    return {
        **state,
        **updates,
        **_fail(state, "tts", f"unexpected audio job status: {final_status}"),
    }


def run_download(
    state: PipelineState,
    *,
    client: CreativeAgentClient,
    settings: OrchestratorSettings,
) -> PipelineState:
    audio_job_id = state.get("audio_job_id")
    if not audio_job_id:
        return {**state, **_fail(state, "download", "download stage missing audio_job_id")}

    dest = settings.output_dir / f"final-{audio_job_id}.mp3"
    download_attempts = state.get("download_attempts", 0)
    last_error: str | None = None

    while True:
        try:
            path = client.download_final_mp3(
                UUID(audio_job_id),
                str(dest),
                correlation_id=state.get("correlation_id"),
            )
            return {
                **state,
                "local_mp3_path": path,
                "stage": "done",
                "log": _log(state, f"saved final mp3: {path}"),
            }
        except (CreativeAgentApiError, OSError) as exc:
            last_error = str(exc)
            status_code = exc.status_code if isinstance(exc, CreativeAgentApiError) else None
            next_attempts = download_attempts + 1
            limit = retry_limit_for_error(
                1,
                third_party_extra=settings.max_third_party_retries,
                message=last_error,
                status_code=status_code,
            )
            download_attempts = next_attempts
            if next_attempts >= limit or not is_transient_third_party_error(
                last_error, status_code=status_code
            ):
                return {
                    **state,
                    **_fail(state, "download", "download failed", last_error=last_error),
                    "download_attempts": download_attempts,
                }
            time.sleep(_backoff_seconds(settings, download_attempts - 1))
            continue
