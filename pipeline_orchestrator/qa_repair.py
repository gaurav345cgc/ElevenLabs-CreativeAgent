"""Phase A: templated FixPlan from compose QA validation_report (no LLM)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


# Deterministic repair lines keyed by validation issue code.
_REPAIR_BY_CODE: dict[str, str] = {
    "session_theme_missing": (
        "Name the session theme in spoken language early (opening or settling) "
        "using concrete life-domain words from the title — not generic calm only."
    ),
    "relatability_keywords_missing": (
        "Weave the missing required keyword groups from the relatability pack into "
        "opening and mind_heart: specific scene nouns for THIS wound (work/tool/body/etc.)."
    ),
    "relatability_opening_weak": (
        "Rewrite OPENING so it lands in this wound's specific scene first "
        "(meeting, screen, body cue, relationship moment) before any generic settle."
    ),
    "relatability_pillar_missing": (
        "Deliver the pillar feel in plain speech (clarity / soften / inquire / etc. "
        "per the brief) — at least one pillar cue phrase in mind_heart or closing."
    ),
    "relatability_forbidden": (
        "Remove forbidden patterns (product codes, diagnose/upskill advice, "
        "or other banned phrases from the pack)."
    ),
    "relatability_better_match": (
        "This draft matches a RIVAL First-10 wound too well. Strip rival scene language; "
        "double down on THIS wound's distinctive cues and life domain only."
    ),
    "relatability_generation_missing": (
        "Add light generation-register cues (years, tenure, judgment, experience language) "
        "without sounding like a demographic lecture."
    ),
    "pain_pillar_wound_weak": (
        "Strengthen wound specificity: opening and mind_heart must feel written for THIS "
        "pain story, not interchangeable calm."
    ),
    "pain_pillar_pillar_mismatch": (
        "Realign to the assigned pillar feel; avoid violating phrases; prefer invite register."
    ),
    "pain_pillar_better_match": (
        "Reduce bleed into another wound; keep scenes and reframes unique to the target product."
    ),
    "pain_pillar_generic": (
        "Replace generic 'just breathe / you are enough' filler with concrete sensory "
        "details from the relatability wound story."
    ),
    "pain_pillar_mind_heart_miss": (
        "In mind_heart, deliver the mind_heart_core distinction (paraphrase OK) for this wound."
    ),
    "composer_guidance_leaked": (
        "Remove composer instruction / use-case meta text; speak only listener-facing narration."
    ),
    "verbatim_example_copy": (
        "Do not copy example excerpts; write a fresh paraphrase in the same tone."
    ),
    "forbidden_meta": (
        "Strip meta markers, wound codes, markdown, and internal taxonomy from narration."
    ),
    "section_too_short": (
        "Expand the short section to at least the minimum spoken words while staying sparse."
    ),
}

_DEFAULT_REPAIR = (
    "Re-read the brief and relatability pack. Fix every listed QA failure with "
    "specific spoken language for this wound and pillar — no generic meditation filler."
)


@dataclass(frozen=True)
class FixPlan:
    summary: str
    root_causes: list[str]
    actions: list[str]
    composer_instructions: str
    should_retry: bool = True
    give_up_reason: str | None = None
    issue_payloads: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _issues_from_report(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not report:
        return []
    raw = report.get("issues") or []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "").lower()
        # Prefer errors; include warns that are relatability/pain so repair is complete.
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        if severity == "error" or code.startswith(("relatability_", "pain_pillar_")):
            out.append(
                {
                    "code": code,
                    "message": str(item.get("message") or ""),
                    "slot": item.get("slot"),
                    "severity": severity or "error",
                }
            )
    return out


def build_fix_plan(validation_report: dict[str, Any] | None) -> FixPlan:
    """Map QA issue codes → templated composer_instructions (deterministic)."""
    issues = _issues_from_report(validation_report)
    error_issues = [i for i in issues if i.get("severity") == "error"] or issues
    codes = []
    for item in error_issues:
        code = item["code"]
        if code not in codes:
            codes.append(code)

    if not codes:
        return FixPlan(
            summary="Compose returned validation failure without actionable issue codes",
            root_causes=[],
            actions=[_DEFAULT_REPAIR],
            composer_instructions=_DEFAULT_REPAIR,
            should_retry=True,
            issue_payloads=issues,
        )

    actions: list[str] = []
    seen_lines: set[str] = set()
    for code in codes:
        line = _REPAIR_BY_CODE.get(code, f"Address QA failure `{code}`.")
        if line not in seen_lines:
            seen_lines.add(line)
            actions.append(line)

    numbered = "\n".join(f"{idx}. {line}" for idx, line in enumerate(actions, start=1))
    summary = "QA failed: " + ", ".join(codes[:6])
    if len(codes) > 6:
        summary += f" (+{len(codes) - 6} more)"

    return FixPlan(
        summary=summary,
        root_causes=codes,
        actions=actions,
        composer_instructions=numbered,
        should_retry=True,
        issue_payloads=error_issues,
    )


def format_qa_failure_message(plan: FixPlan, *, repair_attempts: int, max_attempts: int) -> str:
    lines = [
        f"Compose QA failed after {repair_attempts}/{max_attempts} repair attempt(s).",
        plan.summary,
        "Root causes: " + (", ".join(plan.root_causes) if plan.root_causes else "(none)"),
    ]
    if plan.actions:
        lines.append("Would have repaired with:")
        lines.extend(f"  - {a}" for a in plan.actions[:8])
    return "\n".join(lines)


def write_qa_failure_artifact(
    output_dir: Path,
    *,
    correlation_id: str | None,
    qa_report: dict[str, Any] | None,
    fix_plan: dict[str, Any] | None,
    compose_brief: dict[str, Any] | None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    name = f"qa-failure-{(correlation_id or 'unknown')[:36]}.json"
    path = output_dir / name
    payload = {
        "correlation_id": correlation_id,
        "qa_report": qa_report,
        "fix_plan": fix_plan,
        "compose_brief": {
            k: v
            for k, v in (compose_brief or {}).items()
            if k != "tenant_id"  # still fine to include; keep full for debug
        },
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    return path
