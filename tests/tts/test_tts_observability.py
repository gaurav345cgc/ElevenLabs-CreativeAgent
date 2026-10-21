"""Phase 12 — TTS observability tests."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from observability.tts import (
    InMemoryTtsMetricsSink,
    log_tts_event,
    log_tts_job_completed,
    log_tts_replay,
    record_tts_metric,
    set_tts_metrics_sink,
    tts_context_from_job,
)
from models.enums import AudioJobStatus
from models.records import TranscriptAudioJobRecord


def _job() -> TranscriptAudioJobRecord:
    now = datetime.now(UTC)
    return TranscriptAudioJobRecord(
        id=uuid4(),
        transcript_id=uuid4(),
        transcript_version_id=uuid4(),
        tenant_id=uuid4(),
        idempotency_key="test",
        voice_profile_code="drew_primary",
        voice_id="voice",
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
        status=AudioJobStatus.COMPLETED,
        created_at=now,
        updated_at=now,
    )


def test_log_tts_event_emits_structured_json(caplog) -> None:
    caplog.set_level(logging.INFO, logger="creative_agent.tts")
    log_tts_event(
        "hello",
        event_type="test_event",
        correlation_id="corr-1",
        audio_job_id=str(uuid4()),
    )
    assert len(caplog.records) == 1
    payload = json.loads(caplog.records[0].message)
    assert payload["service"] == "tts"
    assert payload["event_type"] == "test_event"
    assert payload["correlation_id"] == "corr-1"
    assert "audio_job_id" in payload


def test_record_tts_metric_uses_memory_sink() -> None:
    sink = InMemoryTtsMetricsSink()
    set_tts_metrics_sink(sink)
    try:
        record_tts_metric("JobCompleted", audio_job_id=str(uuid4()))
        assert sink.records[0]["metric_name"] == "JobCompleted"
        assert sink.records[0]["value"] == 1.0
    finally:
        set_tts_metrics_sink(None)


def test_tts_context_from_job_includes_core_ids() -> None:
    job = _job()
    context = tts_context_from_job(job, correlation_id="corr-2", chunk_count=13)
    assert context["audio_job_id"] == str(job.id)
    assert context["transcript_id"] == str(job.transcript_id)
    assert context["transcript_version_id"] == str(job.transcript_version_id)
    assert context["voice_id"] == job.voice_id
    assert context["model_id"] == job.model_id
    assert context["status"] == "COMPLETED"
    assert context["chunk_count"] == 13


def test_log_tts_job_completed_records_metric(caplog) -> None:
    sink = InMemoryTtsMetricsSink()
    set_tts_metrics_sink(sink)
    caplog.set_level(logging.INFO, logger="creative_agent.tts")
    try:
        job = _job()
        log_tts_job_completed(**tts_context_from_job(job, correlation_id="corr-3"))
        assert any(record["metric_name"] == "JobCompleted" for record in sink.records)
        payload = json.loads(caplog.records[0].message)
        assert payload["event_type"] == "job_completed"
    finally:
        set_tts_metrics_sink(None)


def test_log_tts_replay_emits_operator_event(caplog) -> None:
    caplog.set_level(logging.INFO, logger="creative_agent.tts")
    log_tts_replay(
        correlation_id="corr-4",
        audio_job_id=str(uuid4()),
        start_state="GenerateChunksSequentially",
    )
    payload = json.loads(caplog.records[0].message)
    assert payload["event_type"] == "operator_replay"
    assert payload["start_state"] == "GenerateChunksSequentially"


def test_log_tts_final_merged_records_metric() -> None:
    from observability.tts import log_tts_final_merged

    sink = InMemoryTtsMetricsSink()
    set_tts_metrics_sink(sink)
    try:
        log_tts_final_merged(
            audio_job_id=str(uuid4()),
            object_key="tenant/transcript/job/final/final.mp3",
            byte_size=1234,
        )
        assert any(record["metric_name"] == "FinalMerged" for record in sink.records)
    finally:
        set_tts_metrics_sink(None)


def test_log_tts_master_mixed_records_metric() -> None:
    from observability.tts import log_tts_master_mixed

    sink = InMemoryTtsMetricsSink()
    set_tts_metrics_sink(sink)
    try:
        log_tts_master_mixed(
            audio_job_id=str(uuid4()),
            transcript_id=str(uuid4()),
            object_key="tenant/transcript/job/final/master.mp3",
            asset_id=str(uuid4()),
            skipped=False,
            byte_size=5678,
            checksum_sha256="master-hash",
            background_profile_code="calm_ambient_01",
            background_track_key="background/calm_ambient_01.mp3",
        )
        assert any(record["metric_name"] == "MasterMixed" for record in sink.records)
    finally:
        set_tts_metrics_sink(None)


def test_log_tts_master_mixed_emits_structured_log_on_skip(caplog) -> None:
    from observability.tts import log_tts_master_mixed

    caplog.set_level(logging.INFO, logger="creative_agent.tts")
    log_tts_master_mixed(
        audio_job_id=str(uuid4()),
        transcript_id=str(uuid4()),
        object_key="tenant/transcript/job/final/master.mp3",
        asset_id=str(uuid4()),
        skipped=True,
        byte_size=100,
        checksum_sha256="master-hash",
        background_profile_code="calm_ambient_01",
        background_track_key="background/calm_ambient_01.mp3",
    )
    payload = json.loads(caplog.records[0].message)
    assert payload["event_type"] == "master_mixed"
    assert payload["skipped"] is True
    assert payload["background_profile_code"] == "calm_ambient_01"


def test_log_tts_pause_plan_created_emits_event_and_hold_metrics(caplog) -> None:
    from observability.tts import log_tts_pause_plan_created

    sink = InMemoryTtsMetricsSink()
    set_tts_metrics_sink(sink)
    caplog.set_level(logging.INFO, logger="creative_agent.tts")
    audio_job_id = str(uuid4())
    transcript_id = str(uuid4())
    try:
        log_tts_pause_plan_created(
            audio_job_id=audio_job_id,
            transcript_id=transcript_id,
            hold_count=3,
            total_hold_seconds=42,
            model="gpt-4o-mini",
            prompt_version="pause-prompt-v1",
            policy_version="pause-v1",
        )
        event_payloads = [json.loads(record.message) for record in caplog.records]
        assert any(payload.get("event_type") == "pause_plan_created" for payload in event_payloads)
        created = next(p for p in event_payloads if p.get("event_type") == "pause_plan_created")
        assert created["audio_job_id"] == audio_job_id
        assert created["transcript_id"] == transcript_id
        assert created["hold_count"] == 3
        assert created["total_hold_seconds"] == 42
        assert created["model"] == "gpt-4o-mini"
        assert created["prompt_version"] == "pause-prompt-v1"
        assert created["policy_version"] == "pause-v1"

        metric_names = {record["metric_name"] for record in sink.records}
        assert "PausePlanCreated" in metric_names
        assert "PauseHoldCount" in metric_names
        assert "PauseHoldSecondsTotal" in metric_names
        hold_seconds = next(r for r in sink.records if r["metric_name"] == "PauseHoldSecondsTotal")
        assert hold_seconds["value"] == 42.0
        assert hold_seconds["unit"] == "Seconds"
    finally:
        set_tts_metrics_sink(None)


def test_log_tts_pause_plan_reused_and_failed_and_latency(caplog) -> None:
    from observability.tts import (
        log_tts_pause_plan_failed,
        log_tts_pause_plan_latency,
        log_tts_pause_plan_reused,
    )

    sink = InMemoryTtsMetricsSink()
    set_tts_metrics_sink(sink)
    caplog.set_level(logging.INFO, logger="creative_agent.tts")
    try:
        log_tts_pause_plan_reused(
            audio_job_id=str(uuid4()),
            transcript_id=str(uuid4()),
            hold_count=1,
            total_hold_seconds=12,
            model="gpt-4o-mini",
            prompt_version="pause-prompt-v1",
            policy_version="pause-v1",
        )
        log_tts_pause_plan_latency(
            audio_job_id=str(uuid4()),
            latency_ms=123.4,
            model="gpt-4o-mini",
        )
        log_tts_pause_plan_failed(
            audio_job_id=str(uuid4()),
            transcript_id=str(uuid4()),
            error="invalid JSON",
            error_type="PausePlannerValidationError",
        )

        event_types = {
            json.loads(record.message).get("event_type")
            for record in caplog.records
            if record.message.startswith("{")
        }
        assert "pause_plan_reused" in event_types
        assert "pause_plan_latency" in event_types
        assert "pause_plan_failed" in event_types

        metric_names = {record["metric_name"] for record in sink.records}
        assert "PausePlanReused" in metric_names
        assert "PausePlanLatencyMs" in metric_names
        assert "PausePlanFailed" in metric_names
        latency = next(r for r in sink.records if r["metric_name"] == "PausePlanLatencyMs")
        assert latency["value"] == 123.4
        assert latency["unit"] == "Milliseconds"
    finally:
        set_tts_metrics_sink(None)


def test_tts_session_scope_emits_db_failure_metric(monkeypatch) -> None:
    from tts_pipeline.persistence import session as tts_session_module
    from tts_pipeline.persistence.session import tts_session_scope

    sink = InMemoryTtsMetricsSink()
    set_tts_metrics_sink(sink)

    @contextmanager
    def failing_scope(*args, **kwargs):
        raise RuntimeError("db down")
        yield  # pragma: no cover

    monkeypatch.setattr(tts_session_module, "session_scope", failing_scope)

    try:
        with pytest.raises(RuntimeError, match="db down"):
            with tts_session_scope(MagicMock(), audio_job_id=str(uuid4())):
                pass
        assert any(record["metric_name"] == "DbWriteFailure" for record in sink.records)
    finally:
        set_tts_metrics_sink(None)
