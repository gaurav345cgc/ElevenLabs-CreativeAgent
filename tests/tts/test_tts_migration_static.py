"""Static checks for TTS audio schema migration (no database required)."""

from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations" / "versions"


def test_tts_migration_module_loads() -> None:
    migration = MIGRATIONS_DIR / "002_tts_audio_schema.py"
    assert migration.exists()
    compile(migration.read_text(encoding="utf-8"), str(migration), "exec")


@pytest.mark.parametrize(
    "name",
    [
        "AUDIO_JOB_STATUS",
        "AUDIO_CHUNK_STATUS",
        "upgrade",
        "downgrade",
    ],
)
def test_tts_migration_defines_expected_symbols(name: str) -> None:
    migration = MIGRATIONS_DIR / "002_tts_audio_schema.py"
    namespace: dict = {}
    exec(compile(migration.read_text(encoding="utf-8"), str(migration), "exec"), namespace)
    assert name in namespace


def test_tts_migration_revision_chain() -> None:
    migration = MIGRATIONS_DIR / "002_tts_audio_schema.py"
    namespace: dict = {}
    exec(compile(migration.read_text(encoding="utf-8"), str(migration), "exec"), namespace)
    assert namespace["revision"] == "002"
    assert namespace["down_revision"] == "001"
