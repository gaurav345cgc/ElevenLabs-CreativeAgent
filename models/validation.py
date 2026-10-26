"""Taxonomy and pattern-plan validation backed by the pattern index."""

from __future__ import annotations

import re

from models.metadata import PatternSlotSelection, SelectedPatternPlan

SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

COMPOSITION_SLOTS: tuple[str, ...] = (
    "opening",
    "settling",
    "body",
    "breath",
    "mind_heart",
    "closing",
)

SUPPORTED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "guided_meditation",
        "breathwork",
        "sleep_story",
    }
)

GENERATION_CODES: frozenset[str] = frozenset(
    {
        "gen_z",
        "millennial",
        "gen_x",
        "boomer",
        "all_generations",
    }
)


def _load_wound_stage_rules() -> dict[str, frozenset[int]]:
    from transcript_composer.knowledge.taxonomy import OVERLAY_WOUND_STAGE_RULES

    rules: dict[str, set[int]] = {
        wound_id: set(stages) for wound_id, stages in OVERLAY_WOUND_STAGE_RULES.items()
    }
    try:
        from transcript_composer.knowledge.loader import load_pattern_index

        for pattern in load_pattern_index().patterns:
            for wound_id in pattern.wound_ids:
                rules.setdefault(wound_id, set()).update(pattern.stage_numbers)
    except (FileNotFoundError, OSError, ValueError):
        pass
    if not rules:
        return {
            "ml_02": frozenset({1, 2, 3, 4, 5, 6}),
            "gz_01": frozenset({1, 2, 3, 4, 5, 6}),
        }
    return {wound_id: frozenset(stages) for wound_id, stages in rules.items()}


def reset_wound_stage_rules_cache() -> None:
    """Clear cached wound/stage rules (call after index reload in tests)."""
    global _WOUND_STAGE_RULES
    _WOUND_STAGE_RULES = None


_WOUND_STAGE_RULES: dict[str, frozenset[int]] | None = None


def get_wound_stage_rules() -> dict[str, frozenset[int]]:
    global _WOUND_STAGE_RULES
    if _WOUND_STAGE_RULES is None:
        _WOUND_STAGE_RULES = _load_wound_stage_rules()
    return _WOUND_STAGE_RULES


class TaxonomyValidationError(ValueError):
    """Raised when brief taxonomy fields are inconsistent or unsupported."""


def _require_slug(value: str, field_name: str) -> None:
    if not SLUG_PATTERN.match(value):
        raise TaxonomyValidationError(
            f"{field_name} must be a lowercase slug (letters, digits, underscores)"
        )


def validate_taxonomy_combination(
    *,
    generation_code: str,
    wound_id: str,
    stage_no: int,
    pillar_code: str | None,
    content_type: str,
) -> None:
    """Validate wound/stage/generation/content_type combinations."""
    _require_slug(generation_code, "generation_code")
    _require_slug(wound_id, "wound_id")
    if pillar_code is not None:
        _require_slug(pillar_code, "pillar_code")
    _require_slug(content_type, "content_type")

    if content_type not in SUPPORTED_CONTENT_TYPES:
        allowed = ", ".join(sorted(SUPPORTED_CONTENT_TYPES))
        raise TaxonomyValidationError(
            f"content_type {content_type!r} is not supported; allowed: {allowed}"
        )

    if generation_code not in GENERATION_CODES:
        allowed = ", ".join(sorted(GENERATION_CODES))
        raise TaxonomyValidationError(
            f"generation_code {generation_code!r} is not supported; allowed: {allowed}"
        )

    if content_type == "guided_meditation":
        allowed_stages = get_wound_stage_rules().get(wound_id)
        if allowed_stages is None:
            known = ", ".join(sorted(get_wound_stage_rules()))
            raise TaxonomyValidationError(
                f"wound_id {wound_id!r} has no stage rules loaded; known wounds: {known}"
            )
        if stage_no not in allowed_stages:
            raise TaxonomyValidationError(
                f"stage_no {stage_no} is not valid for wound_id {wound_id!r}; "
                f"allowed stages: {sorted(allowed_stages)}"
            )


def validate_pattern_plan(plan: SelectedPatternPlan) -> None:
    """Ensure the six-stage plan is complete and ordered."""
    if len(plan.slots) != len(COMPOSITION_SLOTS):
        raise TaxonomyValidationError(
            f"pattern plan must have exactly {len(COMPOSITION_SLOTS)} slots"
        )

    for expected, slot in zip(COMPOSITION_SLOTS, plan.slots, strict=True):
        if slot.slot != expected:
            raise TaxonomyValidationError(
                f"expected slot {expected!r} at position, got {slot.slot!r}"
            )
        _require_slug(slot.pattern_family, f"pattern_family for {slot.slot}")


def build_example_pattern_plan() -> SelectedPatternPlan:
    """Reference six-slot plan from the markdown corpus."""
    families = (
        "guided_meditation_intro",
        "grounding_settling_posture",
        "softening_settling_awareness",
        "breath_attention",
        "mind_reframing_oneness",
        "closing_transition",
    )
    return SelectedPatternPlan(
        slots=[
            PatternSlotSelection(slot=slot, pattern_family=family)
            for slot, family in zip(COMPOSITION_SLOTS, families, strict=True)
        ]
    )
