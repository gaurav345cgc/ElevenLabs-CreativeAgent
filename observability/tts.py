"""Structured logging and metrics for the TTS plane."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

TTS_SERVICE = "tts"
TTS_METRIC_NAMESPACE = "CreativeAgent/TTS"
tts_logger = logging.getLogger("creative_agent.tts")


class TtsMetricsSink(Protocol):
    def record(
        self,
        metric_name: str,
        value: float,
        unit: str,
        *,
        dimensions: dict[str, str],
        context: dict[str, Any],
    ) -> None: ...


@dataclass
class InMemoryTtsMetricsSink:
    """Test helper — captures metric emissions."""

    records: list[dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        metric_name: str,
        value: float,
        unit: str,
        *,
        dimensions: dict[str, str],
        context: dict[str, Any],
    ) -> None:
        self.records.append(
            {
                "metric_name": metric_name,
                "value": value,
                "unit": unit,
                "dimensions": dimensions,
                "context": context,
            }
        )


_metrics_sink: TtsMetricsSink | None = None


def set_tts_metrics_sink(sink: TtsMetricsSink | None) -> None:
    global _metrics_sink
    _metrics_sink = sink


def configure_tts_logging(*, level: int = logging.INFO) -> None:
    """Send structured TTS JSON logs to stderr for local smoke runs and Lambdas."""
    if tts_logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    tts_logger.addHandler(handler)
    tts_logger.setLevel(level)
    tts_logger.propagate = False


def _json_default(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def _base_context(
    *,
    correlation_id: str | None = None,
    audio_job_id: UUID | str | None = None,
    transcript_id: UUID | str | None = None,
    transcript_version_id: UUID | str | None = None,
    chunk_id: UUID | str | None = None,
    chunk_index: int | None = None,
    request_id: str | None = None,
    voice_id: str | None = None,
    model_id: str | None = None,
    status: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    context: dict[str, Any] = {}
    if correlation_id is not None:
        context["correlation_id"] = correlation_id
    if audio_job_id is not None:
        context["audio_job_id"] = str(audio_job_id)
    if transcript_id is not None:
        context["transcript_id"] = str(transcript_id)
    if transcript_version_id is not None:
        context["transcript_version_id"] = str(transcript_version_id)
    if chunk_id is not None:
        context["chunk_id"] = str(chunk_id)
    if chunk_index is not None:
        context["chunk_index"] = chunk_index
    if request_id is not None:
        context["request_id"] = request_id
    if voice_id is not None:
        context["voice_id"] = voice_id
    if model_id is not None:
        context["model_id"] = model_id
    if status is not None:
        context["status"] = status
    context.update(extra)
    return context


def log_tts_event(
    message: str,
    *,
    event_type: str,
    level: int = logging.INFO,
    environment: str | None = None,
    **context: Any,
) -> None:
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": logging.getLevelName(level),
        "service": TTS_SERVICE,
        "event_type": event_type,
        "message": message,
        "environment": environment,
        **context,
    }
    tts_logger.log(level, json.dumps(payload, default=_json_default))


def record_tts_metric(
    metric_name: str,
    value: float = 1.0,
    unit: str = "Count",
    *,
    dimensions: dict[str, str] | None = None,
    **context: Any,
) -> None:
    dims = {"Environment": context.get("environment") or "unknown", **(dimensions or {})}
    if _metrics_sink is not None:
        _metrics_sink.record(metric_name, value, unit, dimensions=dims, context=context)

    emf = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": TTS_METRIC_NAMESPACE,
                    "Dimensions": [list(dims.keys())],
                    "Metrics": [{"Name": metric_name, "Unit": unit}],
                }
            ],
        },
        metric_name: value,
        "service": TTS_SERVICE,
        **dims,
        **context,
    }
    tts_logger.info(json.dumps(emf, default=_json_default))


def log_tts_job_created(**context: Any) -> None:
    log_tts_event("tts audio job created", event_type="job_created", **context)
    record_tts_metric("JobCreated", **context)


def log_tts_job_completed(**context: Any) -> None:
    log_tts_event("tts audio job completed", event_type="job_completed", **context)
    record_tts_metric("JobCompleted", **context)


def log_tts_job_failed(**context: Any) -> None:
    log_tts_event("tts audio job failed", event_type="job_failed", level=logging.ERROR, **context)
    record_tts_metric("JobFailed", **context)


def log_tts_job_partially_failed(**context: Any) -> None:
    log_tts_event(
        "tts audio job partially failed",
        event_type="job_partially_failed",
        level=logging.WARNING,
        **context,
    )
    record_tts_metric("JobPartiallyFailed", **context)


def log_tts_job_review_required(**context: Any) -> None:
    log_tts_event(
        "tts audio job requires operator review",
        event_type="job_review_required",
        level=logging.WARNING,
        **context,
    )
    record_tts_metric("JobReviewRequired", **context)


def log_tts_chunk_completed(**context: Any) -> None:
    log_tts_event("tts chunk completed", event_type="chunk_completed", **context)
    record_tts_metric("ChunkCompleted", **context)


def log_tts_chunk_failed(**context: Any) -> None:
    log_tts_event("tts chunk failed", event_type="chunk_failed", level=logging.ERROR, **context)
    record_tts_metric("ChunkFailed", **context)


def log_tts_chunk_skipped(**context: Any) -> None:
    log_tts_event("tts chunk skipped", event_type="chunk_skipped", **context)
    record_tts_metric("ChunkSkipped", **context)


def log_tts_chunk_retry(**context: Any) -> None:
    log_tts_event("tts chunk synthesis retry", event_type="chunk_retry", level=logging.WARNING, **context)
    record_tts_metric("ChunkRetry", **context)


def log_tts_provider_synthesis(**context: Any) -> None:
    latency_ms = context.get("latency_ms")
    log_tts_event("elevenlabs chunk synthesized", event_type="provider_synthesis", **context)
    if isinstance(latency_ms, (int, float)):
        record_tts_metric("ProviderLatencyMs", float(latency_ms), unit="Milliseconds", **context)


def log_tts_storage_failure(**context: Any) -> None:
    log_tts_event("tts storage write failed", event_type="storage_failure", level=logging.ERROR, **context)
    record_tts_metric("StorageFailure", **context)


def log_tts_db_failure(**context: Any) -> None:
    log_tts_event("tts database write failed", event_type="db_write_failure", level=logging.ERROR, **context)
    record_tts_metric("DbWriteFailure", **context)


def log_tts_workflow_started(**context: Any) -> None:
    log_tts_event("tts workflow started", event_type="workflow_started", **context)


def log_tts_workflow_state(**context: Any) -> None:
    log_tts_event("tts workflow state entered", event_type="workflow_state", **context)


def log_tts_workflow_succeeded(**context: Any) -> None:
    log_tts_event("tts workflow succeeded", event_type="workflow_succeeded", **context)
    record_tts_metric("WorkflowSucceeded", **context)


def log_tts_workflow_failed(**context: Any) -> None:
    log_tts_event("tts workflow failed", event_type="workflow_failed", level=logging.ERROR, **context)
    record_tts_metric("WorkflowFailed", **context)


def log_tts_manifest_finalized(**context: Any) -> None:
    log_tts_event("tts manifest finalized", event_type="manifest_finalized", **context)
    record_tts_metric("ManifestFinalized", **context)


def log_tts_final_merged(**context: Any) -> None:
    log_tts_event("tts final narration merged", event_type="final_merged", **context)
    record_tts_metric("FinalMerged", **context)


def log_tts_master_mixed(**context: Any) -> None:
    log_tts_event("tts master mixed", event_type="master_mixed", **context)
    record_tts_metric("MasterMixed", **context)


def log_tts_replay(**context: Any) -> None:
    """Operator replay / smoke-run diagnostics."""
    log_tts_event("tts operator replay", event_type="operator_replay", **context)


def _record_pause_hold_metrics(**context: Any) -> None:
    hold_count = context.get("hold_count")
    total_hold_seconds = context.get("total_hold_seconds")
    if isinstance(hold_count, (int, float)):
        record_tts_metric("PauseHoldCount", float(hold_count), **context)
    if isinstance(total_hold_seconds, (int, float)):
        record_tts_metric(
            "PauseHoldSecondsTotal",
            float(total_hold_seconds),
            unit="Seconds",
            **context,
        )


def log_tts_pause_plan_created(**context: Any) -> None:
    log_tts_event("tts pause plan created", event_type="pause_plan_created", **context)
    record_tts_metric("PausePlanCreated", **context)
    _record_pause_hold_metrics(**context)


def log_tts_pause_plan_reused(**context: Any) -> None:
    log_tts_event("tts pause plan reused", event_type="pause_plan_reused", **context)
    record_tts_metric("PausePlanReused", **context)
    _record_pause_hold_metrics(**context)


def log_tts_pause_plan_failed(**context: Any) -> None:
    log_tts_event(
        "tts pause plan failed",
        event_type="pause_plan_failed",
        level=logging.ERROR,
        **context,
    )
    record_tts_metric("PausePlanFailed", **context)


def log_tts_pause_plan_latency(**context: Any) -> None:
    latency_ms = context.get("latency_ms")
    log_tts_event("tts pause plan latency", event_type="pause_plan_latency", **context)
    if isinstance(latency_ms, (int, float)):
        record_tts_metric(
            "PausePlanLatencyMs",
            float(latency_ms),
            unit="Milliseconds",
            **context,
        )


def tts_context_from_job(job, *, correlation_id: str | None = None, **extra: Any) -> dict[str, Any]:
    return _base_context(
        correlation_id=correlation_id,
        audio_job_id=job.id,
        transcript_id=job.transcript_id,
        transcript_version_id=job.transcript_version_id,
        voice_id=job.voice_id,
        model_id=job.model_id,
        status=job.status.value if hasattr(job.status, "value") else job.status,
        **extra,
    )


def tts_context_from_chunk(job, chunk, *, correlation_id: str | None = None, **extra: Any) -> dict[str, Any]:
    return _base_context(
        correlation_id=correlation_id,
        audio_job_id=job.id,
        transcript_id=job.transcript_id,
        transcript_version_id=job.transcript_version_id,
        chunk_id=chunk.id,
        chunk_index=chunk.chunk_index,
        request_id=chunk.eleven_request_id,
        voice_id=job.voice_id,
        model_id=job.model_id,
        **extra,
    )
