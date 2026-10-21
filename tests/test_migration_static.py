"""Static checks for migration modules (no database required)."""

from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "db" / "migrations" / "versions"


def test_initial_migration_module_loads() -> None:
    migration = MIGRATIONS_DIR / "001_initial_schema.py"
    assert migration.exists()
    code = migration.read_text(encoding="utf-8")
    compile(code, str(migration), "exec")


@pytest.mark.parametrize(
    "name",
    [
        "TRANSCRIPT_STATUS",
        "VERSION_KIND",
        "ENHANCEMENT_MODE",
        "upgrade",
        "downgrade",
    ],
)
def test_initial_migration_defines_expected_symbols(name: str) -> None:
    migration = MIGRATIONS_DIR / "001_initial_schema.py"
    namespace: dict = {}
    exec(compile(migration.read_text(encoding="utf-8"), str(migration), "exec"), namespace)
    assert name in namespace
