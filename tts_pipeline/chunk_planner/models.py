"""In-memory chunk plan models (before Aurora persistence)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from models.records import TranscriptAudioChunkRecord


class ChunkBoundarySource(StrEnum):
    AGENT2_CHUNKS = "agent2_chunks"
    BEATS = "beats"
    PARAGRAPHS = "paragraphs"
    SENTENCES = "sentences"
    SIZE_SPLIT = "size_split"


@dataclass(frozen=True, slots=True)
class PlannedChunk:
    chunk_index: int
    source_text: str
    previous_text: str | None
    next_text: str | None
    character_count: int
    estimated_duration_ms: int
    boundary_source: ChunkBoundarySource


@dataclass(frozen=True, slots=True)
class ChunkPlanResult:
    audio_job_id: UUID
    boundary_source: ChunkBoundarySource
    chunks: list[PlannedChunk]
    created: bool
    persisted_chunks: list[TranscriptAudioChunkRecord] | None = None
