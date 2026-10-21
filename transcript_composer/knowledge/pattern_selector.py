"""Select pattern families per composition slot from the pattern index."""

from __future__ import annotations

from transcript_composer.knowledge.loader import get_pattern_index
from transcript_composer.knowledge.models import PatternFamilyEntry, PatternSelectionContext
from models.metadata import PatternSlotSelection, SelectedPatternPlan
from models.validation import COMPOSITION_SLOTS, TaxonomyValidationError, validate_pattern_plan


class PatternSelectionError(ValueError):
    """Raised when no pattern can be resolved for a slot."""


class PatternSelector:
    """Deterministic pattern family selection for Agent 1."""

    def __init__(self, index=None) -> None:
        self._index = index or get_pattern_index()

    def _score_pattern(
        self,
        pattern: PatternFamilyEntry,
        context: PatternSelectionContext,
    ) -> int:
        score = 0
        if context.wound_id in pattern.wound_ids:
            score += 8
        if context.stage_no in pattern.stage_numbers:
            score += 6
        if context.generation_code in pattern.generation_codes:
            score += 4
        if context.pillar_code and context.pillar_code in pattern.pillar_codes:
            score += 3
        elif context.pillar_code is None:
            score += 1
        return score

    def candidates_for_slot(
        self,
        slot: str,
        context: PatternSelectionContext,
    ) -> list[PatternFamilyEntry]:
        return [p for p in self._index.patterns if p.composition_slot == slot]

    def select_for_slot(
        self,
        slot: str,
        context: PatternSelectionContext,
    ) -> PatternFamilyEntry:
        candidates = self.candidates_for_slot(slot, context)
        if not candidates:
            raise PatternSelectionError(f"no patterns registered for slot {slot!r}")

        ranked = sorted(
            candidates,
            key=lambda p: (-self._score_pattern(p, context), p.pattern_family),
        )
        best_score = self._score_pattern(ranked[0], context)
        if best_score > 0:
            return ranked[0]

        default_family = self._index.default_pattern_by_slot.get(slot)
        if default_family:
            for pattern in candidates:
                if pattern.pattern_family == default_family:
                    return pattern

        return ranked[0]

    def build_pattern_plan(self, context: PatternSelectionContext) -> SelectedPatternPlan:
        slots = [
            PatternSlotSelection(
                slot=slot,
                pattern_family=self.select_for_slot(slot, context).pattern_family,
            )
            for slot in COMPOSITION_SLOTS
        ]
        plan = SelectedPatternPlan(slots=slots)
        validate_pattern_plan(plan)
        return plan

    def get_pattern_metadata(
        self,
        pattern_family: str,
    ) -> PatternFamilyEntry | None:
        for pattern in self._index.patterns:
            if pattern.pattern_family == pattern_family:
                return pattern
        return None
