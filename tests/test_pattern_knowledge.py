"""Tests for pattern index ingestion, selection, and example retrieval."""

from __future__ import annotations

from models.validation import COMPOSITION_SLOTS, validate_pattern_plan
from transcript_composer.knowledge import (
    ExampleRetriever,
    PatternSelectionContext,
    PatternSelector,
    get_pattern_index,
    load_examples,
    load_pattern_index,
)


def test_pattern_index_loads() -> None:
    index = load_pattern_index()
    assert index.schema_version == "1.0"
    assert len(index.patterns) >= 6
    assert set(index.composition_slots) == set(COMPOSITION_SLOTS)
    guided = next(p for p in index.patterns if p.pattern_family == "guided_meditation_intro")
    assert "introduce journey" in guided.canonical_pattern.lower()


def test_examples_loads() -> None:
    examples = load_examples()
    assert examples.schema_version == "1.0"
    assert len(examples.examples) >= 10


def test_selector_builds_valid_six_stage_plan() -> None:
    selector = PatternSelector()
    context = PatternSelectionContext(
        generation_code="millennial",
        wound_id="ml_02",
        stage_no=2,
        pillar_code="p04",
    )
    plan = selector.build_pattern_plan(context)
    validate_pattern_plan(plan)
    assert plan.slots[0].slot == "opening"
    assert plan.slots[0].pattern_family in {
        p.pattern_family for p in selector.candidates_for_slot("opening", context)
    }
    assert plan.slots[-1].pattern_family == "closing_transition"


def test_selector_prefers_belonging_mind_pattern() -> None:
    selector = PatternSelector()
    context = PatternSelectionContext(
        generation_code="gen_z",
        wound_id="gz_02",
        stage_no=2,
        pillar_code="p06",
    )
    plan = selector.build_pattern_plan(context)
    mind_slot = next(s for s in plan.slots if s.slot == "mind_heart")
    assert mind_slot.pattern_family in {
        "mind_reframing_oneness",
        "mind_reframing_kindness",
        "affirmation_release",
        "affirmation_gratitude",
    }


def test_selector_uses_defaults_when_context_is_sparse() -> None:
    selector = PatternSelector()
    context = PatternSelectionContext(
        generation_code="all_generations",
        wound_id="ml_02",
        stage_no=1,
        pillar_code=None,
    )
    plan = selector.build_pattern_plan(context)
    defaults = get_pattern_index().default_pattern_by_slot
    for slot in plan.slots:
        assert slot.pattern_family in {
            p.pattern_family for p in selector.candidates_for_slot(slot.slot, context)
        }
        assert defaults[slot.slot] is not None


def test_example_retriever_ranks_exact_match_first() -> None:
    context = PatternSelectionContext(
        generation_code="gen_x",
        wound_id="gx_01",
        stage_no=2,
        pillar_code="p01",
    )
    retriever = ExampleRetriever()
    ranked = retriever.rank_examples(
        context,
        pattern_family="softening_settling_awareness",
        placement="settling",
        limit=2,
    )
    assert ranked
    assert ranked[0].example.pattern_family == "softening_settling_awareness"
    assert ranked[0].example.wound_id == "gx_01"
    assert ranked[0].score > ranked[-1].score or len(ranked) == 1


def test_example_retriever_fallback_when_no_close_match() -> None:
    context = PatternSelectionContext(
        generation_code="boomer",
        wound_id="bo_03",
        stage_no=6,
        pillar_code="p05",
    )
    retriever = ExampleRetriever()
    ranked = retriever.rank_examples(
        context,
        pattern_family="nonexistent_pattern",
        placement="opening",
        limit=2,
    )
    assert ranked
    assert ranked[0].match_tier in {"relaxed", "fallback"}


def test_examples_for_plan_returns_all_slots() -> None:
    selector = PatternSelector()
    retriever = ExampleRetriever(selector=selector)
    context = PatternSelectionContext(
        generation_code="millennial",
        wound_id="ml_02",
        stage_no=2,
        pillar_code="p04",
    )
    plan = selector.build_pattern_plan(context)
    refs = retriever.examples_for_plan(context, plan)
    assert set(refs.keys()) == set(COMPOSITION_SLOTS)
    for slot, examples in refs.items():
        assert examples, f"expected at least one example reference for {slot}"
