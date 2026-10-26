"""First-10 overlay wounds are first-class in the pattern index."""

from __future__ import annotations

import json
from pathlib import Path

from models.validation import get_wound_stage_rules, reset_wound_stage_rules_cache, validate_taxonomy_combination
from transcript_composer.knowledge.loader import get_pattern_index, load_pattern_index
from transcript_composer.knowledge.models import PatternSelectionContext
from transcript_composer.knowledge.pattern_selector import PatternSelector
from transcript_composer.knowledge.taxonomy import (
    normalize_wound_id,
    parse_generation_codes,
)
from transcript_composer.relatability import compose_wound_id_for_entry, load_relatability_pack

OVERLAY_WOUNDS = ("wk_04", "wk_05", "wk_06", "ph_01", "ph_03", "fr_01")
BOOST_PATH = (
    Path(__file__).resolve().parents[1]
    / "transcript_composer"
    / "data"
    / "overlay_selector_boost_map.json"
)


def setup_function() -> None:
    get_pattern_index.cache_clear()
    reset_wound_stage_rules_cache()


def test_normalize_overlay_wound_ids() -> None:
    assert normalize_wound_id("WK-04") == "wk_04"
    assert normalize_wound_id("FR-01") == "fr_01"
    assert normalize_wound_id("FR") == "fr_01"


def test_parse_multi_generation_cells() -> None:
    assert parse_generation_codes("Gen X / Millennial") == ["gen_x", "millennial"]
    assert parse_generation_codes("Boomer / Gen X / Millennial") == [
        "boomer",
        "gen_x",
        "millennial",
    ]


def test_index_contains_overlay_wounds() -> None:
    index = load_pattern_index()
    tagged = {wound for pattern in index.patterns for wound in pattern.wound_ids}
    for wound in OVERLAY_WOUNDS:
        assert wound in tagged
    families = {pattern.pattern_family for pattern in index.patterns}
    assert "mind_reframing_distinction" in families
    assert "mind_reframing_open_question" in families
    assert "affirmation_rest_permission" in families


def test_compose_wound_id_prefers_indexed_preferred() -> None:
    pack = load_relatability_pack()
    by_code = {entry["product_code"]: entry for entry in pack["codes"]}
    assert compose_wound_id_for_entry(by_code["WK-06"]) == "wk_06"
    assert compose_wound_id_for_entry(by_code["WK-04"]) == "wk_04"
    assert compose_wound_id_for_entry(by_code["FR"]) == "fr_01"


def test_overlay_taxonomy_validation() -> None:
    validate_taxonomy_combination(
        generation_code="gen_x",
        wound_id="wk_06",
        stage_no=3,
        pillar_code="p05",
        content_type="guided_meditation",
    )
    rules = get_wound_stage_rules()
    assert 2 in rules["ph_03"]
    assert 4 in rules["wk_04"]


def test_selector_matches_boost_map_preferred_variants() -> None:
    boost = json.loads(BOOST_PATH.read_text(encoding="utf-8"))
    selector = PatternSelector()
    cases = [
        ("wk_04", "gen_x", 3, "p02"),
        ("wk_05", "millennial", 4, "p07"),
        ("wk_06", "gen_x", 3, "p05"),
        ("ph_01", "boomer", 2, "p03"),
        ("ph_03", "millennial", 2, "p04"),
        ("fr_01", "gen_z", 2, "p06"),
    ]
    for wound, generation, stage, pillar in cases:
        context = PatternSelectionContext(
            generation_code=generation,
            wound_id=wound,
            stage_no=stage,
            pillar_code=pillar,
        )
        plan = selector.build_pattern_plan(context)
        preferred = boost["wounds"][wound]["variants_by_slot"]
        for slot_selection in plan.slots:
            chosen = next(
                pattern
                for pattern in selector.candidates_for_slot(slot_selection.slot, context)
                if pattern.pattern_family == slot_selection.pattern_family
            )
            assert selector._score_pattern(chosen, context) >= 8
            prefs = preferred.get(slot_selection.slot) or []
            if not prefs:
                continue
            assert slot_selection.pattern_family == prefs[0]
