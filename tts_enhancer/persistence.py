"""Persist Agent 2 output to Aurora."""

from __future__ import annotations

from models.agents import Agent2Output
from models.duration_budget import copy_duration_budget_metadata
from models.enums import TranscriptStatus, VersionKind
from models.messages import EnhancementJobMessage
from models.metadata import EnhancedVersionMetadata
from models.records import TranscriptRecord
from db.repositories import InsertTranscriptVersionInput, TranscriptRepository
from sqlalchemy.orm import Session
from tts_pipeline.background_policy import (
    BACKGROUND_PROFILE_CODE_KEY,
    BACKGROUND_SELECTION_KEY,
    select_background_for_script,
)


def persist_agent2_output(
    repo: TranscriptRepository,
    session: Session,
    *,
    message: EnhancementJobMessage,
    output: Agent2Output,
    correlation_id: str | None = None,
    source_metadata_json: dict | None = None,
    transcript: TranscriptRecord | None = None,
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

    metadata_json = metadata.model_dump(mode="json")
    # OpenAI picks one of the 28 approved beds from script + wound/pillar taxonomy.
    tx = transcript or repo.get_transcript(session, output.transcript_id)
    selection = select_background_for_script(
        content_text=output.enhanced_full_script,
        title=metadata.title,
        content_type=tx.content_type,
        generation_code=tx.generation_code,
        wound_id=tx.wound_id,
        stage_no=tx.stage_no,
        pillar_code=tx.pillar_code,
    )
    metadata_json[BACKGROUND_SELECTION_KEY] = selection
    metadata_json[BACKGROUND_PROFILE_CODE_KEY] = selection["selected_code"]

    repo.insert_transcript_version(
        session,
        InsertTranscriptVersionInput(
            version_id=output.version_id,
            transcript_id=output.transcript_id,
            version_kind=VersionKind.ELEVENLABS_ENHANCED,
            content_text=output.enhanced_full_script,
            content_json=content_json,
            created_by_agent=output.created_by_agent,
            metadata_json=metadata_json,
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
            "background_profile_code": selection.get("selected_code"),
            "background_selected_by": selection.get("selected_by"),
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
