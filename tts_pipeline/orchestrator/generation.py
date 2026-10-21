"""Sequential chunk generation — delegates to generator.chunk_generation (Phase 9)."""

from tts_pipeline.generator.chunk_generation import (
    CHUNK_COMPLETED_EVENT,
    CHUNK_FAILED_EVENT,
    CHUNK_SKIPPED_EVENT,
    ChunkGenerationError,
    ChunkGenerationRunResult,
    generate_chunks_sequentially,
    generate_single_chunk,
)

__all__ = [
    "CHUNK_COMPLETED_EVENT",
    "CHUNK_FAILED_EVENT",
    "CHUNK_SKIPPED_EVENT",
    "ChunkGenerationError",
    "ChunkGenerationRunResult",
    "generate_chunks_sequentially",
    "generate_single_chunk",
]
