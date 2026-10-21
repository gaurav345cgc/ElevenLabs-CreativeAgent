"""Workflow input and result types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from tts_pipeline.intake import CreateAudioJobRequest


class WorkflowState(StrEnum):
    VALIDATE_INPUT = "ValidateInput"
    CREATE_AUDIO_JOB = "CreateAudioJob"
    LOAD_ENHANCED_TRANSCRIPT = "LoadEnhancedTranscript"
    PLAN_PAUSES = "PlanPauses"
    PLAN_CHUNKS = "PlanChunks"
    MAP_PAUSES_TO_CHUNKS = "MapPausesToChunks"
    PERSIST_CHUNK_PLAN = "PersistChunkPlan"
    GENERATE_CHUNKS_SEQUENTIALLY = "GenerateChunksSequentially"
    REGISTER_ASSETS = "RegisterAssets"
    FINALIZE_FINAL = "FinalizeFinal"
    MIX_BACKGROUND = "MixBackground"
    FINALIZE_MANIFEST = "FinalizeManifest"
    MARK_COMPLETED = "MarkCompleted"
    FAILURE_HANDLER = "FailureHandler"
    SUCCEEDED = "Succeeded"


@dataclass(frozen=True, slots=True)
class WorkflowInput:
    audio_job_id: UUID | None = None
    create_job_request: CreateAudioJobRequest | None = None
    start_state: WorkflowState = WorkflowState.VALIDATE_INPUT
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    audio_job_id: UUID
    final_state: WorkflowState
    correlation_id: str
    success: bool
    error: str | None = None
