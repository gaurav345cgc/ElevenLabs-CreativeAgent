"""Rule checks against meditation_patterns_index and meditation_patterns_examples."""

from __future__ import annotations

import re
from typing import Iterable

from models.metadata import SectionedScriptContent
from models.requests import CreateTranscriptRequest
from models.validation import COMPOSITION_SLOTS
from transcript_composer.knowledge.models import (
    ExamplesDocument,
    MeditationExampleEntry,
    PatternFamilyEntry,
    PatternIndexDocument,
    PatternSelectionContext,
)
from transcript_composer.knowledge.pattern_selector import PatternSelector
from transcript_composer.validation.models import ValidationIssue, ValidationSeverity

MIN_SECTION_WORDS = 25
MIN_VERBATIM_CHARS = 48
DURATION_TOLERANCE_ERROR = (0.15, 4.0)
DURATION_TOLERANCE_WARN = (0.45, 2.2)

FORBIDDEN_META_PATTERN = re.compile(
    r"(?:"
    r"pattern_family|canonical pattern|instruction rule|wound_id|"
    r"GZ-\d{2}|ML-\d{2}|GX-\d{2}|BO-\d{2}|WK-\d{2}|PH-\d{2}|\bFR\b|"
    r"```|^\s*#{1,6}\s|\*\*[^*]+\*\*"
    r")",
    re.IGNORECASE | re.MULTILINE,
)
WOUND_SLUG_PATTERN = re.compile(
    r"\b(?:gz|ml|gx|bo|wk|ph|fr)_\d{2}\b",
    re.IGNORECASE,
)
SECTION_LABEL_PATTERN = re.compile(
    r"^\s*(?:opening|settling|body|breath|mind(?:\s+and\s+heart)?|closing)\s*:\s*",
    re.IGNORECASE | re.MULTILINE,
)
COMMANDING_PATTERN = re.compile(
    r"\b(?:breathe|feel|do|stop|must|need to|you should|you have to)\b",
    re.IGNORECASE,
)
INVITE_PATTERN = re.compile(
    r"\b(?:allow|notice|soften|invite|welcome|gently|perhaps|may|can you)\b",
    re.IGNORECASE,
)


def _issue(
    code: str,
    message: str,
    *,
    severity: ValidationSeverity = ValidationSeverity.ERROR,
    slot: str | None = None,
    source: str = "pattern_index",
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=severity,
        message=message,
        slot=slot,
        source=source,
    )


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.strip().lower()))


def _composer_guidance_phrases(*texts: str) -> list[str]:
    phrases: list[str] = []
    for text in texts:
        if not text:
            continue
        for part in re.split(r"[.!?]+", text):
            normalized = _normalize_for_match(part)
            if len(normalized) >= 30:
                phrases.append(normalized)
    return phrases


def check_composer_guidance_leakage(
    sectioned: SectionedScriptContent,
    *,
    pattern_by_family: dict[str, PatternFamilyEntry],
    plan_families: list[tuple[str, str]],
) -> list[ValidationIssue]:
    """Flag when pattern-index instruction_rule or use_case text appears in narration."""
    issues: list[ValidationIssue] = []
    text_by_slot = {
        section.slot: _normalize_for_match(section.text) for section in sectioned.sections
    }
    for slot, family in plan_families:
        pattern = pattern_by_family.get(family)
        if not pattern:
            continue
        section_text = text_by_slot.get(slot, "")
        for phrase in _composer_guidance_phrases(pattern.instruction_rule, pattern.use_case):
            if phrase in section_text:
                issues.append(
                    _issue(
                        "composer_guidance_leaked",
                        "section contains composer instruction or use-case text from the pattern index",
                        slot=slot,
                    )
                )
                break
    return issues


def check_section_structure(sectioned: SectionedScriptContent) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if len(sectioned.sections) != len(COMPOSITION_SLOTS):
        issues.append(
            _issue(
                "section_count",
                f"expected {len(COMPOSITION_SLOTS)} sections, got {len(sectioned.sections)}",
                source="structure",
            )
        )
        return issues

    for expected, section in zip(COMPOSITION_SLOTS, sectioned.sections, strict=True):
        if section.slot != expected:
            issues.append(
                _issue(
                    "section_order",
                    f"expected slot {expected!r}, got {section.slot!r}",
                    slot=section.slot,
                    source="structure",
                )
            )
        words = len(section.text.split())
        if words < MIN_SECTION_WORDS:
            issues.append(
                _issue(
                    "section_too_short",
                    f"section has only {words} words (minimum {MIN_SECTION_WORDS})",
                    slot=section.slot,
                    source="structure",
                )
            )
        if not section.text.strip():
            issues.append(
                _issue(
                    "section_empty",
                    "section text is empty",
                    slot=section.slot,
                    source="structure",
                )
            )
    return issues


def check_pattern_plan_alignment(
    sectioned: SectionedScriptContent,
    *,
    pattern_by_family: dict[str, PatternFamilyEntry],
    plan_families: Iterable[tuple[str, str]],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    section_text_by_slot = {section.slot: section.text for section in sectioned.sections}

    for slot, pattern_family in plan_families:
        pattern = pattern_by_family.get(pattern_family)
        if pattern is None:
            issues.append(
                _issue(
                    "unknown_pattern",
                    f"pattern {pattern_family!r} is not in the index",
                    slot=slot,
                )
            )
            continue
        if pattern.composition_slot != slot:
            issues.append(
                _issue(
                    "pattern_slot_mismatch",
                    f"pattern {pattern_family!r} belongs to slot {pattern.composition_slot!r}, "
                    f"not {slot!r}",
                    slot=slot,
                )
            )
        if pattern_family.replace("_", " ") in section_text_by_slot.get(slot, "").lower():
            issues.append(
                _issue(
                    "pattern_name_leaked",
                    f"pattern name {pattern_family!r} appears in narration text",
                    slot=slot,
                    source="examples",
                )
            )
    return issues


def check_taxonomy_fit(
    context: PatternSelectionContext,
    *,
    pattern_by_family: dict[str, PatternFamilyEntry],
    plan_families: Iterable[tuple[str, str]],
    selector: PatternSelector,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for slot, pattern_family in plan_families:
        pattern = pattern_by_family.get(pattern_family)
        if pattern is None:
            continue
        score = selector._score_pattern(pattern, context)
        if score <= 0:
            issues.append(
                _issue(
                    "taxonomy_weak_fit",
                    f"selected pattern {pattern_family!r} has weak taxonomy fit for "
                    f"{context.generation_code}/{context.wound_id}/stage {context.stage_no}",
                    slot=slot,
                    severity=ValidationSeverity.WARN,
                )
            )
        elif score < 8:
            issues.append(
                _issue(
                    "taxonomy_partial_fit",
                    f"selected pattern {pattern_family!r} only partially matches brief taxonomy",
                    slot=slot,
                    severity=ValidationSeverity.WARN,
                )
            )
    return issues


def check_duration(
    request: CreateTranscriptRequest,
    *,
    duration_seconds: int,
) -> list[ValidationIssue]:
    """Validate *spoken* length against the speech share of wall-clock target.

    Intentional pause holds fill the remaining share later; Agent 1 must not
    write a full wall-clock of words or holds get crushed.
    """
    from models.duration_budget import build_session_duration_budget

    budget = build_session_duration_budget(request.target_duration_minutes)
    target = budget.speech_budget_seconds
    if target <= 0:
        return []
    ratio = duration_seconds / target
    low_err, high_err = DURATION_TOLERANCE_ERROR
    low_warn, high_warn = DURATION_TOLERANCE_WARN

    if ratio < low_err or ratio > high_err:
        return [
            _issue(
                "duration_out_of_range",
                f"estimated speech {duration_seconds}s is far from speech budget "
                f"{target}s (wall-clock {budget.target_duration_seconds}s includes "
                f"~{budget.hold_budget_seconds}s hold room)",
                source="structure",
            )
        ]
    if ratio < low_warn or ratio > high_warn:
        return [
            _issue(
                "duration_drift",
                f"estimated speech {duration_seconds}s drifts from speech budget "
                f"{target}s (wall-clock target {request.target_duration_minutes} min)",
                severity=ValidationSeverity.WARN,
                source="structure",
            )
        ]
    return []


def check_narration_hygiene(sectioned: SectionedScriptContent) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for section in sectioned.sections:
        text = section.text
        if FORBIDDEN_META_PATTERN.search(text):
            issues.append(
                _issue(
                    "forbidden_meta",
                    "section contains meta markers, wound codes, or markdown",
                    slot=section.slot,
                    source="examples",
                )
            )
        if WOUND_SLUG_PATTERN.search(text):
            issues.append(
                _issue(
                    "wound_code_leaked",
                    "section contains internal wound taxonomy codes",
                    slot=section.slot,
                    source="examples",
                )
            )
        if SECTION_LABEL_PATTERN.search(text):
            issues.append(
                _issue(
                    "section_label_leaked",
                    "section contains structural labels instead of spoken narration",
                    slot=section.slot,
                    source="examples",
                )
            )
    return issues


def check_invite_register(sectioned: SectionedScriptContent) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for section in sectioned.sections:
        commanding = len(COMMANDING_PATTERN.findall(section.text))
        inviting = len(INVITE_PATTERN.findall(section.text))
        if commanding >= 4 and commanding > inviting * 2:
            issues.append(
                _issue(
                    "commanding_register",
                    "section sounds commanding rather than invitational "
                    "(examples corpus prefers allow/notice/soften language)",
                    slot=section.slot,
                    severity=ValidationSeverity.WARN,
                    source="examples",
                )
            )
    return issues


def check_verbatim_examples(
    transcript_text: str,
    examples: ExamplesDocument,
    *,
    pattern_families: set[str],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    normalized_transcript = _normalize_for_match(transcript_text)

    for example in examples.examples:
        if example.pattern_family not in pattern_families:
            continue
        excerpt = _normalize_for_match(example.reference_excerpt)
        if len(excerpt) < MIN_VERBATIM_CHARS:
            continue
        if excerpt in normalized_transcript:
            issues.append(
                _issue(
                    "verbatim_example_copy",
                    f"transcript copies example excerpt for pattern {example.pattern_family!r} "
                    f"({example.example_id})",
                    severity=ValidationSeverity.ERROR,
                    source="examples",
                )
            )
    return issues


def check_session_theme(
    request: CreateTranscriptRequest,
    sectioned: SectionedScriptContent,
) -> list[ValidationIssue]:
    """If the title implies work/pain/friendship, spoken text must reflect that frame."""
    from transcript_composer.theme import required_theme_keywords, session_title

    keywords = required_theme_keywords(request)
    if not keywords:
        return []

    full = " ".join(section.text for section in sectioned.sections).lower()
    if any(re.search(rf"\b{re.escape(word)}\b", full) for word in keywords):
        return []

    title = session_title(request)
    return [
        _issue(
            "session_theme_missing",
            f"spoken script never reflects the session title theme {title!r}; "
            f"expected at least one of: {', '.join(keywords[:8])}",
            severity=ValidationSeverity.ERROR,
            source="session_theme",
        )
    ]


def _phrase_hits(text_lower: str, phrases: Iterable[str]) -> list[str]:
    hits: list[str] = []
    for phrase in phrases:
        token = (phrase or "").strip().lower()
        if not token:
            continue
        if " " in token or "-" in token:
            if token in text_lower:
                hits.append(token)
        elif re.search(rf"\b{re.escape(token)}\b", text_lower):
            hits.append(token)
    return hits


def _group_satisfied(text_lower: str, group: Iterable[str]) -> bool:
    return bool(_phrase_hits(text_lower, group))


def _keyword_group_hit_count(text_lower: str, groups: Iterable[Iterable[str]]) -> int:
    return sum(1 for group in groups if _group_satisfied(text_lower, group))


def _check_fail_if_better_matches(
    *,
    product: str,
    full: str,
    spec: dict,
) -> list[ValidationIssue]:
    """Fail when the script matches a rival First-10 wound as well or better than the target.

    Deterministic floor against cross-wound bleed (no LLM). Rival criteria come only
    from the relatability pack — never invented.
    """
    rivals = spec.get("fail_if_better_matches") or []
    if not rivals:
        return []

    from transcript_composer.relatability import entry_by_product_code

    current_groups = list(spec.get("required_keyword_groups") or [])
    current_hits = _keyword_group_hit_count(full, current_groups)
    current_total = len(current_groups) or 1
    issues: list[ValidationIssue] = []

    for rival_code in rivals:
        rival_entry = entry_by_product_code(str(rival_code))
        if rival_entry is None:
            continue
        rival_product = str(rival_entry.get("product_code") or rival_code).upper()
        if rival_product == str(product).upper():
            continue
        rival_spec = rival_entry.get("validator") or {}
        rival_groups = list(rival_spec.get("required_keyword_groups") or [])
        if not rival_groups:
            continue
        rival_hits = _keyword_group_hit_count(full, rival_groups)
        rival_total = len(rival_groups)
        rival_half = max(1, (rival_total + 1) // 2)
        rival_complete = rival_hits >= rival_total
        current_incomplete = current_hits < current_total

        better = rival_hits > current_hits and rival_hits >= rival_half
        equal_complete = rival_complete and rival_hits >= current_hits and rival_total >= 2
        complete_while_target_weak = rival_complete and current_incomplete

        if better or equal_complete or complete_while_target_weak:
            issues.append(
                _issue(
                    "relatability_better_match",
                    f"relatability pack {product}: script matches rival {rival_product} "
                    f"as well or better ({rival_hits}/{rival_total} rival keyword groups vs "
                    f"{current_hits}/{current_total} for target)",
                    severity=ValidationSeverity.ERROR,
                    source="relatability",
                )
            )
    return issues


def check_relatability_pack(
    request: CreateTranscriptRequest,
    sectioned: SectionedScriptContent,
) -> list[ValidationIssue]:
    """Enforce First-10 relatability pack validator seeds when a code matches."""
    from transcript_composer.relatability import relatability_validator_spec

    spec = relatability_validator_spec(request)
    if not spec:
        return []

    issues: list[ValidationIssue] = []
    product = spec.get("product_code", "?")
    full = " ".join(section.text for section in sectioned.sections).lower()
    opening = next(
        (section.text.lower() for section in sectioned.sections if section.slot == "opening"),
        "",
    )

    for pattern in spec.get("forbidden_patterns") or []:
        token = (pattern or "").strip().lower()
        if not token:
            continue
        if " " in token:
            found = token in full
        else:
            found = bool(re.search(rf"\b{re.escape(token)}\b", full))
        if found:
            issues.append(
                _issue(
                    "relatability_forbidden",
                    f"relatability pack {product}: forbidden pattern {pattern!r} appears in script",
                    severity=ValidationSeverity.ERROR,
                    source="relatability",
                )
            )

    missing_groups: list[str] = []
    for index, group in enumerate(spec.get("required_keyword_groups") or [], start=1):
        if not _group_satisfied(full, group):
            sample = ", ".join(list(group)[:4])
            missing_groups.append(f"group{index} ({sample})")
    if missing_groups:
        issues.append(
            _issue(
                "relatability_keywords_missing",
                f"relatability pack {product}: missing required keyword groups: "
                + "; ".join(missing_groups),
                severity=ValidationSeverity.ERROR,
                source="relatability",
            )
        )

    min_open = int(spec.get("min_opening_theme_hits") or 0)
    if min_open > 0:
        open_groups = spec.get("required_keyword_groups") or []
        open_hits = 0
        # Count distinct group hits in opening (prefer first two groups as theme anchors).
        for group in open_groups[:2]:
            if _group_satisfied(opening, group):
                open_hits += 1
        if open_hits < min_open:
            issues.append(
                _issue(
                    "relatability_opening_weak",
                    f"relatability pack {product}: opening needs at least "
                    f"{min_open} theme keyword-group hit(s); found {open_hits}",
                    severity=ValidationSeverity.ERROR,
                    source="relatability",
                )
            )

    for index, group in enumerate(spec.get("pillar_required_keyword_groups") or [], start=1):
        if not _group_satisfied(full, group):
            sample = ", ".join(list(group)[:4])
            issues.append(
                _issue(
                    "relatability_pillar_missing",
                    f"relatability pack {product}: pillar cue group{index} missing "
                    f"(need one of: {sample})",
                    severity=ValidationSeverity.ERROR,
                    source="relatability",
                )
            )

    for index, group in enumerate(spec.get("generation_required_keyword_groups") or [], start=1):
        if not _group_satisfied(full, group):
            sample = ", ".join(list(group)[:4])
            issues.append(
                _issue(
                    "relatability_generation_missing",
                    f"relatability pack {product}: generation cue group{index} missing "
                    f"(need one of: {sample})",
                    severity=ValidationSeverity.WARN,
                    source="relatability",
                )
            )

    issues.extend(_check_fail_if_better_matches(product=str(product), full=full, spec=spec))
    return issues



def check_canonical_beats(
    sectioned: SectionedScriptContent,
    *,
    pattern_by_family: dict[str, PatternFamilyEntry],
    plan_families: Iterable[tuple[str, str]],
) -> list[ValidationIssue]:
    """Light check: at least one canonical beat keyword appears per section."""
    issues: list[ValidationIssue] = []
    section_text = {section.slot: section.text.lower() for section in sectioned.sections}

    for slot, pattern_family in plan_families:
        pattern = pattern_by_family.get(pattern_family)
        if pattern is None or not pattern.canonical_pattern:
            continue
        beats = [
            beat.strip().lower()
            for beat in re.split(r"[→]+", pattern.canonical_pattern)
            if beat.strip()
        ]
        if not beats:
            continue
        text = section_text.get(slot, "")
        matched = sum(1 for beat in beats if _beat_present(beat, text))
        if matched == 0 and len(beats) >= 2:
            issues.append(
                _issue(
                    "canonical_beats_missing",
                    f"section may not follow canonical beats for {pattern_family!r} "
                    f"({pattern.canonical_pattern})",
                    slot=slot,
                    severity=ValidationSeverity.WARN,
                )
            )
    return issues


def _beat_present(beat: str, text: str) -> bool:
    tokens = [token for token in re.findall(r"[a-z]{4,}", beat) if token not in {"into", "with", "from", "that", "this"}]
    if not tokens:
        return False
    hits = sum(1 for token in tokens if token in text)
    return hits >= max(1, len(tokens) // 2)
