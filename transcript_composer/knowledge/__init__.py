"""Pattern index and examples knowledge base for Agent 1."""

from transcript_composer.knowledge.example_retriever import ExampleRetriever
from transcript_composer.knowledge.loader import get_examples, get_pattern_index, load_examples, load_pattern_index
from transcript_composer.knowledge.models import (
    MeditationExampleEntry,
    PatternFamilyEntry,
    PatternIndexDocument,
    PatternSelectionContext,
    RankedExample,
)
from transcript_composer.knowledge.pattern_selector import PatternSelector, PatternSelectionError

__all__ = [
    "ExampleRetriever",
    "MeditationExampleEntry",
    "PatternFamilyEntry",
    "PatternIndexDocument",
    "PatternSelectionContext",
    "PatternSelectionError",
    "PatternSelector",
    "RankedExample",
    "get_examples",
    "get_pattern_index",
    "load_examples",
    "load_pattern_index",
]
