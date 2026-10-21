"""OpenAI-based transcript validation against pattern index and examples."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from models.agents import Agent1Output
from models.requests import CreateTranscriptRequest
from transcript_composer.knowledge.models import ExamplesDocument, PatternFamilyEntry
from transcript_composer.llm_config import (
    ensure_dotenv_loaded,
    require_openai_api_key,
    resolve_openai_model,
)
from transcript_composer.validation.models import (
    TranscriptValidationReport,
    ValidationIssue,
    ValidationSeverity,
)

SYSTEM_PROMPT = """You are a quality reviewer for Agent 1 (Pattern Transcript Composer).

Your job: decide whether a generated meditation transcript follows the authoritative sources:
- meditation_patterns_index.md (structure, pattern families, canonical beats, instruction rules)
- meditation_patterns_examples.md (invitational tone, pace, no verbatim copying)

Return JSON only. Be strict on errors that would break production or violate therapeutic guardrails.
Use warnings for softer issues (weak beat coverage, slightly commanding tone, duration drift).

Severity guide:
- error: wrong structure, wrong pattern for slot, meta/markdown in narration, verbatim example copy,
  wound codes in text, pattern names in text, pattern-index instruction_rule or use_case pasted into narration,
  clearly wrong therapeutic intent
- warn: partial taxonomy fit, weak canonical beat coverage, slightly commanding tone, duration drift

Issue codes (use these when applicable):
section_count, section_order, section_too_short, pattern_slot_mismatch, pattern_name_leaked,
forbidden_meta, composer_guidance_leaked, wound_code_leaked, verbatim_example_copy, commanding_register, canonical_beats_missing,
taxonomy_weak_fit, duration_drift, therapeutic_intent_mismatch, tone_mismatch"""


class _LlmIssuePayload(BaseModel):
    code: str
    severity: Literal["error", "warn"]
    message: str
    slot: str | None = None


class _LlmValidationPayload(BaseModel):
    passed: bool
    issues: list[_LlmIssuePayload] = Field(default_factory=list)


class OpenAITranscriptValidator:
    """LLM reviewer for composed transcripts."""

    _COERCE_TO_WARN = frozenset(
        {
            # These are quality signals but should not block composition end-to-end.
            "duration_drift",
            "commanding_register",
            "canonical_beats_missing",
            "taxonomy_weak_fit",
            "tone_mismatch",
        }
    )

    def __init__(
        self,
        *,
        client: Any | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        ensure_dotenv_loaded()
        self._model = model or resolve_openai_model()
        self._client = client or self._build_client(api_key or require_openai_api_key())

    def validate(
        self,
        request: CreateTranscriptRequest,
        output: Agent1Output,
        *,
        pattern_by_family: dict[str, PatternFamilyEntry],
        examples: ExamplesDocument,
        fail_on_warning: bool = False,
    ) -> TranscriptValidationReport:
        prompt = _build_validation_prompt(
            request=request,
            output=output,
            pattern_by_family=pattern_by_family,
            examples=examples,
        )
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("OpenAI returned empty validation response")
        payload = _LlmValidationPayload.model_validate(json.loads(content))
        issues = [
            ValidationIssue(
                code=item.code,
                severity=ValidationSeverity.WARN
                if item.code in self._COERCE_TO_WARN
                else (
                    ValidationSeverity.ERROR
                    if item.severity == "error"
                    else ValidationSeverity.WARN
                ),
                message=item.message,
                slot=item.slot,
                source="llm",
            )
            for item in payload.issues
        ]
        error_count = sum(1 for i in issues if i.severity == ValidationSeverity.ERROR)
        warning_count = sum(1 for i in issues if i.severity == ValidationSeverity.WARN)
        # The LLM's `passed` is advisory only; the pipeline uses issue severities.
        passed = error_count == 0 and (warning_count == 0 or not fail_on_warning)
        return TranscriptValidationReport(
            passed=passed,
            error_count=error_count,
            warning_count=warning_count,
            issues=issues,
        )

    @staticmethod
    def _build_client(api_key: str) -> Any:
        from openai import OpenAI

        return OpenAI(api_key=api_key)


def _build_validation_prompt(
    *,
    request: CreateTranscriptRequest,
    output: Agent1Output,
    pattern_by_family: dict[str, PatternFamilyEntry],
    examples: ExamplesDocument,
) -> str:
    plan_lines = []
    example_blocks = []
    used_families = {slot.pattern_family for slot in output.pattern_plan.slots}

    for slot_selection in output.pattern_plan.slots:
        pattern = pattern_by_family.get(slot_selection.pattern_family)
        if pattern:
            plan_lines.append(
                f"- {slot_selection.slot} → `{slot_selection.pattern_family}`\n"
                f"  canonical_pattern: {pattern.canonical_pattern}\n"
                f"  instruction_rule: {pattern.instruction_rule}\n"
                f"  use_case: {pattern.use_case}\n"
                f"  tone_notes: {pattern.tone_notes or '(none)'}"
            )

    for example in examples.examples:
        if example.pattern_family not in used_families:
            continue
        example_blocks.append(
            f"### {example.pattern_family} / {example.example_id}\n"
            f"guidance: {example.pattern_guidance or example.use_case}\n"
            f"excerpt (must NOT be copied verbatim): {example.reference_excerpt[:400]}"
        )

    sections = "\n\n".join(
        f"## [{section.slot}]\n{section.text}" for section in output.sectioned_script.sections
    )

    return f"""Review this Agent 1 transcript.

## Brief
- generation: {request.generation_code}
- wound_id: {request.wound_id}
- stage: {request.stage_no}
- pillar: {request.pillar_code or '(none)'}
- target_duration_minutes: {request.target_duration_minutes}
- estimated_duration_seconds: {output.duration_estimate.seconds}

## Selected pattern plan (from index)
{chr(10).join(plan_lines)}

## Example tone reference (do not allow verbatim copy)
{chr(10).join(example_blocks[:12]) or '(no examples loaded)'}

## Generated transcript (sectioned)
{sections}

## Required JSON shape
{{
  "passed": true,
  "issues": [
    {{"code": "tone_mismatch", "severity": "warn", "message": "...", "slot": "settling"}}
  ]
}}

Set passed=false if any error-severity issue exists."""


def validation_mode_label(mode: str) -> str:
    return mode if mode in {"openai", "rules", "hybrid"} else "rules"
