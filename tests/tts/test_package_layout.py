"""TTS plane package layout — matches architecture-and-tts-plane.md §6."""

from pathlib import Path

import tts_pipeline
from tts_pipeline import (
    chunk_planner,
    finalizer,
    generator,
    intake,
    orchestrator,
    persistence,
    voice_policy,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TTS_ROOT = REPO_ROOT / "tts_pipeline"

EXPECTED_MODULES = (
    "intake",
    "orchestrator",
    "chunk_planner",
    "generator",
    "finalizer",
    "voice_policy",
    "persistence",
)


def test_tts_pipeline_root_exists():
    assert TTS_ROOT.is_dir()


def test_tts_pipeline_submodules_importable():
    for name in EXPECTED_MODULES:
        assert getattr(tts_pipeline, name) is not None


def test_each_module_is_package_with_init():
    for name in EXPECTED_MODULES:
        init_file = TTS_ROOT / name / "__init__.py"
        assert init_file.is_file(), f"missing {init_file}"


def test_submodules_are_distinct():
    modules = [
        intake,
        orchestrator,
        chunk_planner,
        generator,
        finalizer,
        voice_policy,
        persistence,
    ]
    assert len({id(m) for m in modules}) == len(modules)
