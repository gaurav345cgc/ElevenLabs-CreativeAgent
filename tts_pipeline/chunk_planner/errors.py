"""Chunk planning errors."""


class ChunkPlanningError(Exception):
    """Base error for chunk planning."""


class ChunkPlanValidationError(ChunkPlanningError):
    """Planned chunks violate size or boundary rules."""
