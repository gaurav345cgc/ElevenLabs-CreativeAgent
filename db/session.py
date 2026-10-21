"""Transaction helpers and retry-safe session management."""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import TypeVar

from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from db.engine import create_db_engine

T = TypeVar("T")

RETRYABLE_PG_CODES = frozenset({"40001", "40P01", "55P03"})


def is_retryable_db_error(exc: BaseException) -> bool:
    if isinstance(exc, OperationalError):
        orig = getattr(exc, "orig", None)
        pgcode = getattr(orig, "pgcode", None)
        return pgcode in RETRYABLE_PG_CODES
    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return True
    return False


@contextmanager
def session_scope(
    session_factory: sessionmaker[Session],
    *,
    max_retries: int = 3,
    retry_backoff_seconds: float = 0.05,
) -> Generator[Session, None, None]:
    """Commit on success, rollback on error; retry transient serialization/deadlock errors."""
    attempt = 0
    while True:
        session = session_factory()
        try:
            yield session
            session.commit()
            return
        except Exception as exc:
            session.rollback()
            if attempt < max_retries and is_retryable_db_error(exc):
                attempt += 1
                time.sleep(retry_backoff_seconds * attempt)
                continue
            raise
        finally:
            session.close()


def build_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    engine = create_db_engine(database_url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
