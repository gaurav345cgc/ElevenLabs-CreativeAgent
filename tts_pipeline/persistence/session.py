"""TTS session scope with observability on terminal DB failures."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from db.session import session_scope
from observability.tts import log_tts_db_failure


@contextmanager
def tts_session_scope(
    session_factory: sessionmaker[Session],
    *,
    correlation_id: str | None = None,
    audio_job_id: UUID | str | None = None,
    max_retries: int = 3,
    retry_backoff_seconds: float = 0.05,
) -> Generator[Session, None, None]:
    """Commit on success; emit TTS DB failure metric/log after retries are exhausted."""
    try:
        with session_scope(
            session_factory,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        ) as session:
            yield session
    except Exception as exc:
        log_tts_db_failure(
            correlation_id=correlation_id,
            audio_job_id=str(audio_job_id) if audio_job_id is not None else None,
            error_type=type(exc).__name__,
            error_message=str(exc)[:500],
        )
        raise
