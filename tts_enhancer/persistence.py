"""Persist Agent 2 output to Aurora."""

from __future__ import annotations

from models.agents import Agent2Output
from models.duration_budget import copy_duration_budget_metadata
from models.enums import TranscriptStatus, VersionKind
from models.messages import EnhancementJobMessage
from models.metadata import EnhancedVersionMetadata
from db.repositories import InsertTranscriptVersionInput, TranscriptRepository
from sqlalchemy.orm import Session


def persist_agent2_output(
    repo: TranscriptRepository,
    session: Session,
    *,
    message: EnhancementJobMessage,
    output: Agent2Output,
    correlation_id: str | None = None,
    source_metadata_json: dict | None = None,
) -> Agent2Output:
    """Insert ELEVENLABS_ENHANCED version and mark transcript ENHANCED."""
    metadata = EnhancedVersionMetadata(
        source_version_id=output.source_version_id,
        voice_model=message.voice_model,
        enhancement_mode=message.requested_output_mode,
        duration_estimate=output.duration_estimate,
        voice_direction_notes=output.voice_direction_notes,
        pronunciation_notes=output.pronunciation_notes,
        title=_title_from_source_metadata(source_metadata_json),
        **copy_duration_budget_metadata(source_metadata_json),
    )
    content_json = output.enhanced_content.model_dump(mode="json")
    if output.sectioned_script is not None:
        content_json["sectioned_script"] = output.sectioned_script.model_dump(mode="json")

    repo.insert_transcript_version(
        session,
        InsertTranscriptVersionInput(
            version_id=output.version_id,
            transcript_id=output.transcript_id,
            version_kind=VersionKind.ELEVENLABS_ENHANCED,
            content_text=output.enhanced_full_script,
            content_json=content_json,
            created_by_agent=output.created_by_agent,
            metadata_json=metadata.model_dump(mode="json"),
            source_version_id=output.source_version_id,
            enhancement_mode=message.requested_output_mode,
        ),
        correlation_id=correlation_id,
    )
    repo.set_current_version(
        session,
        output.transcript_id,
        output.version_id,
        correlation_id=correlation_id,
    )
    repo.update_transcript_status(
        session,
        output.transcript_id,
        TranscriptStatus.ENHANCED,
        correlation_id=correlation_id,
    )
    repo.record_job_event(
        session,
        output.transcript_id,
        "ENHANCEMENT_COMPLETED",
        {
            "enhanced_version_id": str(output.version_id),
            "raw_version_id": str(output.source_version_id),
            "enhancement_mode": message.requested_output_mode.value,
            "voice_model": message.voice_model,
        },
        correlation_id=correlation_id,
    )
    return output


def _title_from_source_metadata(source_metadata_json: dict | None) -> str | None:
    if not isinstance(source_metadata_json, dict):
        return None
    raw = source_metadata_json.get("title")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()[:512]
    return None
