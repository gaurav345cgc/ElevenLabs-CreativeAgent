"""Map pause-plan hold anchors onto TTS chunk indices."""

from __future__ import annotations

import logging
import re

from tts_pipeline.chunk_planner.models import PlannedChunk
from tts_pipeline.pause_planner.anchors import PauseAnchors
from tts_pipeline.pause_planner.errors import PausePlannerValidationError
from tts_pipeline.pause_planner.policy import clamp_hold_seconds
from tts_pipeline.pause_planner.schema import (
    MappedPauseHold,
    MappedPausePlan,
    PauseHold,
    PauseHoldKind,
    PausePlan,
)

logger = logging.getLogger("creative_agent.tts.pause_planner")

_WS_RE = re.compile(r"\s+")

# Highest severity first for merge selection.
_KIND_SEVERITY: tuple[PauseHoldKind, ...] = (
    PauseHoldKind.INTEGRATION,
    PauseHoldKind.SECTION,
    PauseHoldKind.PRACTICE,
    PauseHoldKind.OTHER,
)


def map_pause_plan_to_chunks(
    plan: PausePlan,
    chunks: list[PlannedChunk],
    anchors: PauseAnchors,
) -> MappedPausePlan:
    """Translate beat/paragraph holds onto ``after_chunk_index`` values.

    Deterministic for the same inputs. No OpenAI dependency.
    """
    if not chunks:
        raise PausePlannerValidationError("cannot map pause plan: chunk list is empty")

    units = _speech_units(anchors)
    if not units:
        raise PausePlannerValidationError("cannot map pause plan: anchors have no speech units")

    chunk_of_unit = _assign_units_to_chunks(units, chunks)
    mapped: list[MappedPauseHold] = []

    for hold in plan.holds:
        unit_index = _hold_unit_index(hold, anchors)
        if unit_index < 0 or unit_index >= len(units):
            raise PausePlannerValidationError(
                f"hold {hold.hold_id!r} unit index {unit_index} out of range "
                f"for {len(units)} {anchors.preferred}"
            )
        after_chunk_index = chunk_of_unit[unit_index]
        if after_chunk_index < 0 or after_chunk_index >= len(chunks):
            raise PausePlannerValidationError(
                f"hold {hold.hold_id!r} mapped to invalid chunk index {after_chunk_index}"
            )
        mapped.append(
            MappedPauseHold(
                hold_id=hold.hold_id,
                after_beat_index=hold.after_beat_index,
                after_paragraph_index=hold.after_paragraph_index,
                after_chunk_index=after_chunk_index,
                hold_seconds=hold.hold_seconds,
                kind=hold.kind,
                reason=hold.reason,
            )
        )

    merged = _merge_holds_on_same_chunk(mapped)
    merged.sort(key=lambda hold: (hold.after_chunk_index, hold.hold_id))
    return MappedPausePlan(total_hold_seconds=0, holds=merged)


def _speech_units(anchors: PauseAnchors) -> list[str]:
    if anchors.preferred == "beats":
        return list(anchors.beats)
    return list(anchors.paragraphs)


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", text.strip())


def _hold_unit_index(hold: PauseHold, anchors: PauseAnchors) -> int:
    if anchors.preferred == "beats":
        if hold.after_beat_index is None:
            raise PausePlannerValidationError(
                f"hold {hold.hold_id!r} missing after_beat_index for beats anchors"
            )
        return hold.after_beat_index
    if hold.after_paragraph_index is None:
        raise PausePlannerValidationError(
            f"hold {hold.hold_id!r} missing after_paragraph_index for paragraphs anchors"
        )
    return hold.after_paragraph_index


def _assign_units_to_chunks(
    units: list[str],
    chunks: list[PlannedChunk],
) -> list[int]:
    """Return chunk_index for each unit index (greedy containment, then proportional)."""
    normalized_chunks = [_normalize_ws(chunk.source_text) for chunk in chunks]
    assignment: list[int | None] = [None] * len(units)
    search_from = 0

    for unit_index, unit in enumerate(units):
        needle = _normalize_ws(unit)
        if not needle:
            continue
        placed = False
        for chunk_pos in range(search_from, len(chunks)):
            if needle in normalized_chunks[chunk_pos]:
                assignment[unit_index] = chunks[chunk_pos].chunk_index
                search_from = chunk_pos
                placed = True
                break
        if not placed:
            # Restart from beginning for out-of-order containment recovery.
            for chunk_pos, haystack in enumerate(normalized_chunks):
                if needle in haystack:
                    assignment[unit_index] = chunks[chunk_pos].chunk_index
                    search_from = chunk_pos
                    placed = True
                    break
        if not placed:
            logger.warning(
                "pause mapping containment failed for unit_index=%s; using proportional fallback",
                unit_index,
            )
            assignment = _proportional_assignment(units, chunks)
            return assignment

    if any(value is None for value in assignment):
        logger.warning("pause mapping incomplete after containment; using proportional fallback")
        return _proportional_assignment(units, chunks)

    return [int(value) for value in assignment]  # type: ignore[arg-type]


def _proportional_assignment(units: list[str], chunks: list[PlannedChunk]) -> list[int]:
    """Assign units in order proportional to chunk character counts."""
    total_chars = sum(max(1, chunk.character_count) for chunk in chunks)
    unit_count = len(units)
    if unit_count == 0:
        return []

    # Build cumulative character boundaries across chunks, then map unit midpoints.
    boundaries: list[tuple[int, int, int]] = []  # (start, end, chunk_index)
    cursor = 0
    for chunk in chunks:
        width = max(1, chunk.character_count)
        boundaries.append((cursor, cursor + width, chunk.chunk_index))
        cursor += width

    assignment: list[int] = []
    for unit_index in range(unit_count):
        # Place unit at proportional position in the character span.
        position = int(((unit_index + 0.5) / unit_count) * total_chars)
        chosen = chunks[-1].chunk_index
        for start, end, chunk_index in boundaries:
            if start <= position < end:
                chosen = chunk_index
                break
        assignment.append(chosen)
    return assignment


def _merge_holds_on_same_chunk(holds: list[MappedPauseHold]) -> list[MappedPauseHold]:
    by_chunk: dict[int, list[MappedPauseHold]] = {}
    for hold in holds:
        by_chunk.setdefault(hold.after_chunk_index, []).append(hold)

    merged: list[MappedPauseHold] = []
    for after_chunk_index, group in by_chunk.items():
        if len(group) == 1:
            merged.append(group[0])
            continue

        kind = _highest_severity_kind(hold.kind for hold in group)
        total_seconds = sum(hold.hold_seconds for hold in group)
        clamped = clamp_hold_seconds(total_seconds, kind)
        reasons = "; ".join(hold.reason for hold in group)
        if len(reasons) > 240:
            reasons = reasons[:237] + "..."

        first = group[0]
        # Prefer first non-null beat/paragraph from the group for audit.
        after_beat = next((h.after_beat_index for h in group if h.after_beat_index is not None), None)
        after_paragraph = next(
            (h.after_paragraph_index for h in group if h.after_paragraph_index is not None),
            None,
        )
        # MappedPauseHold requires exactly one source anchor.
        if after_beat is not None:
            after_paragraph = None
        elif after_paragraph is None:
            raise PausePlannerValidationError(
                f"merged holds on chunk {after_chunk_index} have no source anchor"
            )

        hold_id = first.hold_id if len({h.hold_id for h in group}) == 1 else f"merged_c{after_chunk_index}"
        merged.append(
            MappedPauseHold(
                hold_id=hold_id,
                after_beat_index=after_beat,
                after_paragraph_index=after_paragraph,
                after_chunk_index=after_chunk_index,
                hold_seconds=clamped,
                kind=kind,
                reason=reasons,
            )
        )
        logger.info(
            "merged %s holds onto chunk_index=%s seconds=%s kind=%s",
            len(group),
            after_chunk_index,
            clamped,
            kind.value,
        )
    return merged


def _highest_severity_kind(kinds) -> PauseHoldKind:
    kind_set = set(kinds)
    for kind in _KIND_SEVERITY:
        if kind in kind_set:
            return kind
    return PauseHoldKind.OTHER
