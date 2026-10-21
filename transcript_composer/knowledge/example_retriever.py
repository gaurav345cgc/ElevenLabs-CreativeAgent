"""Retrieve ranked meditation examples for tone and register guidance."""

from __future__ import annotations

from transcript_composer.knowledge.loader import get_examples
from transcript_composer.knowledge.models import (
    MeditationExampleEntry,
    PatternSelectionContext,
    RankedExample,
)
from transcript_composer.knowledge.pattern_selector import PatternSelector
from models.metadata import SelectedPatternPlan


class ExampleRetriever:
    """Rank examples for Agent 1 style reference (not copy source)."""

    def __init__(self, examples=None, selector: PatternSelector | None = None) -> None:
        self._examples = examples or get_examples()
        self._selector = selector or PatternSelector()

    def _score_example(
        self,
        example: MeditationExampleEntry,
        context: PatternSelectionContext,
        *,
        pattern_family: str | None = None,
        placement: str | None = None,
    ) -> int:
        score = 0
        if pattern_family and example.pattern_family == pattern_family:
            score += 12
        if placement and example.placement == placement:
            score += 8
        if example.wound_id == context.wound_id:
            score += 6
        if example.stage_no == context.stage_no:
            score += 5
        if example.generation_code == context.generation_code:
            score += 4
        elif example.generation_code == "all_generations":
            score += 2
        if context.pillar_code and example.pillar_code == context.pillar_code:
            score += 3
        return score

    def _match_tier(
        self,
        example: MeditationExampleEntry,
        context: PatternSelectionContext,
        *,
        pattern_family: str | None = None,
        placement: str | None = None,
    ) -> str:
        if example.example_id.startswith("generic_") and example.example_id.endswith("_fallback"):
            return "fallback"

        family_match = bool(pattern_family and example.pattern_family == pattern_family)
        placement_match = bool(placement and example.placement == placement)
        context_match = (
            example.wound_id == context.wound_id
            or example.stage_no == context.stage_no
            or example.generation_code == context.generation_code
        )

        if family_match and placement_match and context_match:
            return "exact"
        if family_match or (placement_match and context_match):
            return "relaxed"
        return "fallback"

    def rank_examples(
        self,
        context: PatternSelectionContext,
        *,
        pattern_family: str | None = None,
        placement: str | None = None,
        limit: int = 3,
    ) -> list[RankedExample]:
        scored: list[RankedExample] = []
        for example in self._examples.examples:
            score = self._score_example(
                example,
                context,
                pattern_family=pattern_family,
                placement=placement,
            )
            if score > 0:
                scored.append(
                    RankedExample(
                        example=example,
                        score=score,
                        match_tier=self._match_tier(
                            example,
                            context,
                            pattern_family=pattern_family,
                            placement=placement,
                        ),
                    )
                )

        scored.sort(key=lambda item: (-item.score, item.example.example_id))
        if scored:
            if pattern_family and not any(
                item.example.pattern_family == pattern_family for item in scored
            ):
                return self._fallback_examples(placement=placement, limit=limit)
            return scored[:limit]

        return self._fallback_examples(placement=placement, limit=limit)

    def _fallback_examples(
        self,
        *,
        placement: str | None,
        limit: int,
    ) -> list[RankedExample]:
        """Use generic fallback examples when no close match exists."""
        fallback_ids = {
            "opening": "generic_opening_fallback",
            "closing": "generic_closing_fallback",
        }
        results: list[RankedExample] = []
        for example in self._examples.examples:
            if placement and example.placement == placement:
                results.append(RankedExample(example=example, score=1, match_tier="relaxed"))
            elif example.example_id in fallback_ids.values():
                results.append(RankedExample(example=example, score=0, match_tier="fallback"))

        results.sort(key=lambda item: (-item.score, item.example.example_id))
        return results[:limit]

    def examples_for_plan(
        self,
        context: PatternSelectionContext,
        plan: SelectedPatternPlan,
        *,
        per_slot: int = 1,
    ) -> dict[str, list[RankedExample]]:
        references: dict[str, list[RankedExample]] = {}
        for slot in plan.slots:
            pattern_family = slot.pattern_family
            pattern = self._selector.get_pattern_metadata(pattern_family)
            placement = pattern.composition_slot if pattern else slot.slot
            references[slot.slot] = self.rank_examples(
                context,
                pattern_family=pattern_family,
                placement=placement,
                limit=per_slot,
            )
        return references
