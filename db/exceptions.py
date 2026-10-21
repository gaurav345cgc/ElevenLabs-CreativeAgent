"""Database layer exceptions."""


class RepositoryError(Exception):
    """Base error for persistence operations."""


class TranscriptNotFoundError(RepositoryError):
    """Transcript row does not exist."""


class StateTransitionError(RepositoryError):
    """Status transition is not allowed or row did not match expected state."""


class DuplicateVersionError(RepositoryError):
    """Immutable version already exists for this enhancement strategy."""


class TranscriptVersionNotFoundError(RepositoryError):
    """Transcript version row does not exist or does not belong to the transcript."""


class DuplicateAudioJobError(RepositoryError):
    """Audio job idempotency key already exists."""


class AudioJobNotFoundError(RepositoryError):
    """Audio job row does not exist."""
