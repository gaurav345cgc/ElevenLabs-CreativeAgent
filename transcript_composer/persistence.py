"""Persist Agent 1 output to Aurora."""

from __future__ import annotations

from models.agents import Agent1Output
from models.enums import TranscriptStatus, VersionKind
from models.requests import CreateTranscriptRequest
from db.repositories import CreateTranscriptInput, InsertTranscriptVersionInput, TranscriptRepository
from sqlalchemy.orm import Session


def persist_agent1_output(
    repo: TranscriptRepository,
    session: Session,
    *,
    request: CreateTranscriptRequest,
    output: Agent1Output,
    correlation_id: str | None = None,
) -> Agent1Output:
    """Insert transcript + RAW_PATTERN version and mark PENDING_ENHANCEMENT."""
    repo.create_transcript(
        session,
        CreateTranscriptInput(
            transcript_id=output.transcript_id,
            tenant_id=request.tenant_id,
            asset_id=request.asset_id,
            content_type=request.content_type,
            generation_code=request.generation_code,
            wound_id=request.wound_id,
            stage_no=request.stage_no,
            pillar_code=request.pillar_code,
            status=TranscriptStatus.CREATED,
        ),
        correlation_id=correlation_id,
    )
    repo.insert_transcript_version(
        session,
        InsertTranscriptVersionInput(
            version_id=output.version_id,
            transcript_id=output.transcript_id,
            version_kind=VersionKind.RAW_PATTERN,
            content_text=output.transcript_text,
            content_json=output.sectioned_script.model_dump(mode="json"),
            created_by_agent=output.created_by_agent,
            metadata_json=output.metadata.model_dump(mode="json"),
        ),
        correlation_id=correlation_id,
    )
    repo.update_transcript_status(
        session,
        output.transcript_id,
        TranscriptStatus.PENDING_ENHANCEMENT,
        correlation_id=correlation_id,
    )
    repo.record_job_event(
        session,
        output.transcript_id,
        "TRANSCRIPT_QUEUED",
        {
            "raw_version_id": str(output.version_id),
            "requested_output_mode": request.requested_output_mode.value,
            "voice_model": request.voice_model,
        },
        correlation_id=correlation_id,
    )
    return output
