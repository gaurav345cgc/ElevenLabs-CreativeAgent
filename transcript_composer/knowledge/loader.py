"""Load pattern index and examples from JSON or markdown resources."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from transcript_composer.knowledge.md_parser import parse_examples_markdown, parse_pattern_index_markdown
from transcript_composer.knowledge.models import ExamplesDocument, PatternIndexDocument

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

PATTERN_INDEX_CANDIDATES = (
    DATA_DIR / "meditation_patterns_index.md",
    DATA_DIR / "meditation_patterns_index (1).md",
    DATA_DIR / "meditation_patterns_index.json",
)
EXAMPLES_CANDIDATES = (
    DATA_DIR / "meditation_patterns_examples.md",
    DATA_DIR / "meditation_patterns_examples (1).md",
    DATA_DIR / "meditation_patterns_examples.json",
)


def _resolve_existing(candidates: tuple[Path, ...]) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    names = ", ".join(str(path.name) for path in candidates)
    raise FileNotFoundError(f"no pattern resource found in {DATA_DIR}; expected one of: {names}")


def load_pattern_index(path: Path | None = None) -> PatternIndexDocument:
    source = path or _resolve_existing(PATTERN_INDEX_CANDIDATES)
    if source.suffix.lower() == ".md":
        return parse_pattern_index_markdown(source.read_text(encoding="utf-8"))
    payload = json.loads(source.read_text(encoding="utf-8"))
    return PatternIndexDocument.model_validate(payload)


def load_examples(path: Path | None = None) -> ExamplesDocument:
    source = path or _resolve_existing(EXAMPLES_CANDIDATES)
    if source.suffix.lower() == ".md":
        return parse_examples_markdown(source.read_text(encoding="utf-8"))
    payload = json.loads(source.read_text(encoding="utf-8"))
    return ExamplesDocument.model_validate(payload)


@lru_cache(maxsize=1)
def get_pattern_index() -> PatternIndexDocument:
    return load_pattern_index()


@lru_cache(maxsize=1)
def get_examples() -> ExamplesDocument:
    return load_examples()
