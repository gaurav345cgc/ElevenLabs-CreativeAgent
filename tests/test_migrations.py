"""Schema migration tests — requires local Postgres (docker compose up -d)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = (
    "postgresql://creative_agent:creative_agent@localhost:5432/creative_agent"
)


def _database_url() -> str:
    return os.environ.get("CREATIVE_AGENT_DATABASE_URL", DEFAULT_DATABASE_URL)


def _postgres_reachable() -> bool:
    try:
        engine = create_engine(_database_url(), pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="Postgres not reachable — set CREATIVE_AGENT_DATABASE_URL in .env or environment",
)


@requires_postgres
def test_migrations_upgrade_and_downgrade() -> None:
    env = {**os.environ, "CREATIVE_AGENT_DATABASE_URL": _database_url()}
    alembic = [sys.executable, "-m", "alembic", "-c", "db/alembic.ini"]

    subprocess.run(
        [*alembic, "downgrade", "base"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [*alembic, "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    engine = create_engine(_database_url())
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    assert tables >= {
        "transcript",
        "transcript_version",
        "transcript_job_event",
        "transcript_audio_job",
        "transcript_audio_chunk",
        "transcript_audio_asset",
        "transcript_audio_event",
    }

    transcript_cols = {c["name"] for c in inspector.get_columns("transcript")}
    assert {
        "id",
        "tenant_id",
        "asset_id",
        "status",
        "current_version_id",
        "enhancement_attempt_count",
        "last_error",
    } <= transcript_cols

    version_cols = {c["name"] for c in inspector.get_columns("transcript_version")}
    assert {"source_version_id", "enhancement_mode", "version_kind", "content_text"} <= version_cols

    indexes = {idx["name"] for idx in inspector.get_indexes("transcript")}
    assert "ix_transcript_status" in indexes
    assert "ix_transcript_tenant_id" in indexes

    job_cols = {c["name"] for c in inspector.get_columns("transcript_audio_job")}
    assert {
        "transcript_id",
        "transcript_version_id",
        "status",
        "final_asset_id",
        "idempotency_key",
        "retry_count",
        "failure_notes",
    } <= job_cols

    chunk_uniques = {
        uc["name"]
        for uc in inspector.get_unique_constraints("transcript_audio_chunk")
    }
    assert "uq_transcript_audio_chunk_job_index" in chunk_uniques

    chunk_indexes = {idx["name"] for idx in inspector.get_indexes("transcript_audio_chunk")}
    assert "ix_transcript_audio_chunk_audio_job_id" in chunk_indexes
    assert "ix_transcript_audio_chunk_status" in chunk_indexes

    subprocess.run(
        [*alembic, "downgrade", "-1"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
