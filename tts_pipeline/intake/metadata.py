"""Build traceability metadata persisted on audio jobs."""

from __future__ import annotations

from typing import Any

from models.duration_budget import copy_duration_budget_metadata
from models.records import TranscriptRecord, TranscriptVersionRecord
from tts_pipeline.background_policy import copy_background_metadata


def build_audio_job_metadata(
    *,
    transcript: TranscriptRecord,
    transcript_version: TranscriptVersionRecord,
    voice_profile_code: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    version_meta = transcript_version.metadata_json or {}
    # Top-level duration fields so PlanPauses resolves wall-clock without digging.
    metadata: dict[str, Any] = {
        **copy_duration_budget_metadata(version_meta),
        **copy_background_metadata(version_meta),
        "traceability": {
            "transcript": {
                "content_type": transcript.content_type,
                "generation_code": transcript.generation_code,
                "wound_id": transcript.wound_id,
                "stage_no": transcript.stage_no,
                "pillar_code": transcript.pillar_code,
                "current_version_id": str(transcript.current_version_id)
                if transcript.current_version_id
                else None,
            },
            "transcript_version": {
                "created_by_agent": transcript_version.created_by_agent,
                "enhancement_mode": transcript_version.enhancement_mode.value
                if transcript_version.enhancement_mode
                else None,
                "source_version_id": str(transcript_version.source_version_id)
                if transcript_version.source_version_id
                else None,
                "metadata_json": transcript_version.metadata_json,
            },
            "voice_profile_code": voice_profile_code,
            "correlation_id": correlation_id,
        },
    }
    # Carry Script Hub human pause plan onto the job for operators / manifests.
    if version_meta.get("human_pause_plan") is not None:
        metadata["human_pause_plan"] = version_meta["human_pause_plan"]
        if version_meta.get("human_pause_hold_count") is not None:
            metadata["human_pause_hold_count"] = version_meta["human_pause_hold_count"]
        if version_meta.get("human_pause_total_hold_seconds") is not None:
            metadata["human_pause_total_hold_seconds"] = version_meta[
                "human_pause_total_hold_seconds"
            ]
    return metadata
