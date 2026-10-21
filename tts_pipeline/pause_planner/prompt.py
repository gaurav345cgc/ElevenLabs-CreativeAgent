"""Pause planner prompts and response parsing (Phase 4 contract).

Bump ``PROMPT_VERSION`` in ``policy.py`` when changing prompt text so stored plans
can be distinguished for idempotent replan semantics.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from tts_pipeline.pause_planner.errors import PausePlannerValidationError
from tts_pipeline.pause_planner.policy import (
    KIND_BOUNDS,
    MAX_HOLD_SECONDS,
    MAX_HOLDS_PER_JOB,
    MIN_HOLD_SECONDS,
    PAUSE_POLICY_VERSION,
    PROMPT_VERSION,
)
from tts_pipeline.pause_planner.schema import (
    PauseHold,
    PauseHoldKind,
    PausePlan,
    PausePlannerProvider,
)

# Documented JSON shape returned by the model (holds only — metadata is server-side).
RESPONSE_SCHEMA_EXAMPLE = {
    "holds": [
        {
            "hold_id": "h1",
            "after_beat_index": 3,
            "hold_seconds": 12,
            "kind": "practice",
            "reason": "Time to soften shoulders",
        }
    ]
}


def build_system_prompt() -> str:
    kinds = ", ".join(kind.value for kind in PauseHoldKind)
    return f"""You are a meditation pause planner for guided audio production.

Your job: decide WHERE the voice should stop and for HOW MANY SECONDS so the listener can practice or rest, while background music continues.

Product goal: realistic mindfulness audio — the voice must breathe. Continuous speech feels like a lecture.
Hard density rule: place a silence hold after EVERY spoken sentence (never more than 1 sentence without a hold).
Default: short practice hold (~2–5s) after each numbered beat/sentence. Prefer too many short rests over too few.

Output rules (strict):
- Return JSON only. Top-level object with key "holds" (array).
- Do NOT rewrite, shorten, add, or paraphrase any spoken narration text.
- Do NOT output spoken stage directions like "(pause 4 seconds)".
- Each hold must include: hold_id, hold_seconds, kind, reason, and exactly ONE anchor:
  - after_beat_index when the user message provides beats
  - after_paragraph_index when the user message provides paragraphs only

Placement rules:
- After almost every beat/sentence that contains spoken guidance, add a practice hold (typically 2–5s).
- Hard cap: never allow 2 spoken sentences in a row without a silence hold.
- After the brief welcome/intro, you may use a longer section rest before main practice begins.
- Also place longer section/integration holds at major stage changes and before closing.
- Skip a hold only for a pure connective fragment with no absorbable cue (e.g. "And now," alone) — and never skip twice in a row.
- Spend most of the hold budget on many short rests; do not save silence for one long closing pause.

Timing rules:
- hold_seconds must be between {MIN_HOLD_SECONDS} and {MAX_HOLD_SECONDS}.
- At most {MAX_HOLDS_PER_JOB} holds.
- kind must be one of: {kinds}.
- Agent 1 already sized spoken text so speech + holds ≈ wall-clock target — spend the hold_budget_seconds.
- Aim for sum(hold_seconds) ≥ 85% of hold_budget_seconds; distribute across the script, not one closing pause.
- If over budget, scale hold lengths down before dropping holds.
- reason: short operational note (why the listener needs silence), max one sentence.

Reference: prompt_version={PROMPT_VERSION} policy_version={PAUSE_POLICY_VERSION}."""


def build_user_prompt(
    *,
    beats: list[str],
    paragraphs: list[str],
    target_duration_seconds: int,
    estimated_speech_seconds: int,
) -> str:
    if not beats and not paragraphs:
        raise PausePlannerValidationError("beats or paragraphs are required for user prompt")

    remaining = max(0, target_duration_seconds - estimated_speech_seconds)
    lines: list[str] = [
        "Plan silence holds for this enhanced meditation script.",
        "",
        f"target_duration_seconds (WALL-CLOCK including holds): {target_duration_seconds}",
        f"estimated_speech_seconds: {estimated_speech_seconds}",
        f"hold_budget_seconds (aim total holds ≈ this): {remaining}",
        "",
        "TIMING CONTRACT (coordinated with Agent 1):",
        "  speech + sum(hold_seconds) ≈ target_duration_seconds",
        "  Agent 1 already sized spoken text to leave this hold budget — use it.",
        "  Prefer spending ≥85% of hold_budget_seconds across practice/section/integration holds.",
        "  Do not leave the middle as a word wall while banking silence only at the end.",
        "",
        "Policy bounds by kind:",
    ]
    for kind, bounds in KIND_BOUNDS.items():
        lines.append(
            f"  - {kind.value}: clamp {bounds.min_seconds}-{bounds.max_seconds}s "
            f"(prefer {bounds.prefer_min}-{bounds.prefer_max}s)"
        )

    lines.extend(
        [
            "",
            "HARD DENSITY RULE: silence hold after EVERY spoken sentence (max 1 sentence without a hold).",
            "Default: a short practice hold after nearly every numbered beat (2–5s each).",
            "Spend most of the hold budget on many short rests — realistic meditation pacing.",
            "",
            "Good vs bad placement (examples):",
            "  GOOD: after welcome sentence → short hold, then after next sentence → hold again",
            "  GOOD: after 'Let your shoulders soften.' → 2-5s practice hold",
            "  GOOD: after the very next sentence → another 2-5s hold (this frequency is correct)",
            "  GOOD: after intro block → 10-20s section hold before main practice",
            "  GOOD: before closing → longer integration hold",
            "  BAD: 2+ sentences of continuous speech with no hold",
            "  BAD: only a handful of holds for a multi-minute script",
            "  BAD: saving silence for the end while the middle is a word wall",
            "",
        ]
    )

    if beats:
        lines.append("Use after_beat_index only. Numbered beats:")
        for index, beat in enumerate(beats):
            lines.append(f"{index}: {beat.strip()}")
    else:
        lines.append("Use after_paragraph_index only. Numbered paragraphs:")
        for index, paragraph in enumerate(paragraphs):
            lines.append(f"{index}: {paragraph.strip()}")

    lines.extend(
        [
            "",
            "Respond with JSON matching this shape (metadata like planner/model is NOT needed):",
            json.dumps(RESPONSE_SCHEMA_EXAMPLE, indent=2),
        ]
    )
    return "\n".join(lines)


def parse_pause_plan_response(
    raw: dict[str, Any],
    *,
    model: str,
    target_duration_seconds: int | None,
    estimated_speech_seconds: int | None,
    raw_response_bytes: bytes | None = None,
    use_beats: bool,
) -> PausePlan:
    """Map OpenAI JSON into ``PausePlan``; assign provider metadata server-side."""
    holds_raw = raw.get("holds")
    if holds_raw is None:
        holds_raw = []
    if not isinstance(holds_raw, list):
        raise PausePlannerValidationError("pause planner 'holds' must be an array")

    holds: list[PauseHold] = []
    for index, item in enumerate(holds_raw):
        if not isinstance(item, dict):
            raise PausePlannerValidationError(f"holds[{index}] must be an object")
        holds.append(_parse_hold_item(item, index=index, use_beats=use_beats))

    sha256 = None
    if raw_response_bytes is not None:
        sha256 = hashlib.sha256(raw_response_bytes).hexdigest()

    try:
        return PausePlan(
            planner=PausePlannerProvider.OPENAI,
            model=model,
            prompt_version=PROMPT_VERSION,
            policy_version=PAUSE_POLICY_VERSION,
            target_duration_seconds=target_duration_seconds,
            estimated_speech_seconds=estimated_speech_seconds,
            total_hold_seconds=0,
            holds=holds,
            raw_response_sha256=sha256,
        )
    except ValidationError as exc:
        raise PausePlannerValidationError(f"invalid pause plan payload: {exc}") from exc


def _parse_hold_item(item: dict[str, Any], *, index: int, use_beats: bool) -> PauseHold:
    hold_id = item.get("hold_id")
    if not hold_id or not str(hold_id).strip():
        hold_id = f"h{index + 1}"
    kind_raw = item.get("kind", "practice")
    try:
        kind = PauseHoldKind(str(kind_raw))
    except ValueError as exc:
        raise PausePlannerValidationError(f"holds[{index}] invalid kind: {kind_raw!r}") from exc

    reason = item.get("reason")
    if not reason or not str(reason).strip():
        raise PausePlannerValidationError(f"holds[{index}] requires non-empty reason")

    hold_seconds = item.get("hold_seconds")
    if hold_seconds is None:
        raise PausePlannerValidationError(f"holds[{index}] requires hold_seconds")

    after_beat = item.get("after_beat_index")
    after_paragraph = item.get("after_paragraph_index")

    if use_beats:
        if after_beat is None and after_paragraph is not None:
            after_beat = after_paragraph
        if after_beat is None:
            raise PausePlannerValidationError(
                f"holds[{index}] requires after_beat_index when beats are provided"
            )
        return PauseHold(
            hold_id=str(hold_id).strip(),
            after_beat_index=int(after_beat),
            after_paragraph_index=None,
            hold_seconds=int(hold_seconds),
            kind=kind,
            reason=str(reason).strip()[:240],
        )

    if after_paragraph is None and after_beat is not None:
        after_paragraph = after_beat
    if after_paragraph is None:
        raise PausePlannerValidationError(
            f"holds[{index}] requires after_paragraph_index when only paragraphs are provided"
        )
    return PauseHold(
        hold_id=str(hold_id).strip(),
        after_beat_index=None,
        after_paragraph_index=int(after_paragraph),
        hold_seconds=int(hold_seconds),
        kind=kind,
        reason=str(reason).strip()[:240],
    )
