"""Validate Agent 1 output against pattern index and examples corpus."""

from __future__ import annotations

from models.agents import Agent1Output
from models.requests import CreateTranscriptRequest
from transcript_composer.knowledge.loader import get_examples
from transcript_composer.knowledge.models import PatternSelectionContext
from transcript_composer.knowledge.pattern_selector import PatternSelector
from transcript_composer.llm_config import (
    resolve_openai_api_key,
    resolve_validation_mode,
)
from transcript_composer.validation.llm_validator import OpenAITranscriptValidator
from transcript_composer.validation.models import TranscriptValidationReport, ValidationSeverity
from transcript_composer.validation.pain_pillar_agent import (
    PainPillarAgent,
    run_pain_pillar_qa,
)
from transcript_composer.validation.rules import (
    check_canonical_beats,
    check_composer_guidance_leakage,
    check_duration,
    check_invite_register,
    check_narration_hygiene,
    check_pattern_plan_alignment,
    check_relatability_pack,
    check_section_structure,
    check_session_theme,
    check_taxonomy_fit,
    check_verbatim_examples,
)


class TranscriptValidationError(ValueError):
    """Raised when generated transcript fails mandatory pattern validation."""

    def __init__(self, message: str, *, report: TranscriptValidationReport) -> None:
        super().__init__(message)
        self.report = report


def _resolve_mode(validation_mode: str | None) -> str:
    mode = (validation_mode or resolve_validation_mode()).strip().lower()
    if mode == "auto":
        return "openai" if resolve_openai_api_key() else "rules"
    if mode in {"openai", "rules"}:
        return mode
    return "rules"


class TranscriptValidator:
    """Check composed transcript against meditation_patterns_index and _examples."""

    def __init__(
        self,
        *,
        selector: PatternSelector | None = None,
        validation_mode: str | None = None,
        llm_validator: OpenAITranscriptValidator | None = None,
        pain_pillar_agent: PainPillarAgent | None = None,
    ) -> None:
        self._selector = selector or PatternSelector()
        self._index = self._selector._index
        self._examples = get_examples()
        self._pattern_by_family = {
            pattern.pattern_family: pattern for pattern in self._index.patterns
        }
        self._mode = _resolve_mode(validation_mode)
        self._llm_validator = llm_validator
        self._pain_pillar_agent = pain_pillar_agent

    @property
    def validation_mode(self) -> str:
        return self._mode

    def validate(
        self,
        request: CreateTranscriptRequest,
        output: Agent1Output,
        *,
        fail_on_warning: bool = False,
    ) -> TranscriptValidationReport:
        plan_pairs = [(slot.slot, slot.pattern_family) for slot in output.pattern_plan.slots]
        # Always-on hard floor (both openai and rules modes).
        hard_issues = [
            *check_section_structure(output.sectioned_script),
            *check_session_theme(request, output.sectioned_script),
            *check_relatability_pack(request, output.sectioned_script),
            *check_composer_guidance_leakage(
                output.sectioned_script,
                pattern_by_family=self._pattern_by_family,
                plan_families=plan_pairs,
            ),
            *check_verbatim_examples(
                output.transcript_text,
                self._examples,
                pattern_families={slot.pattern_family for slot in output.pattern_plan.slots},
            ),
            *run_pain_pillar_qa(
                request,
                output,
                agent=self._pain_pillar_agent,
            ),
        ]

        if self._mode == "openai":
            qualitative = self._validate_with_openai(
                request,
                output,
                fail_on_warning=fail_on_warning,
            )
            # Qualitative LLM reviewer stays advisory; pain_pillar_qa is separate and
            # already evidence-gated inside hard_issues.
            qualitative = _downgrade_llm_errors_to_warnings(qualitative)
            report = _merge_reports(hard_issues, qualitative, fail_on_warning=fail_on_warning)
            return report.model_copy(update={"validator": "openai"})

        rule_issues = self._validate_with_rules(request, output)
        # Merge always-on hard checks with the rest of the rules engine (dedupe by
        # code+message+slot so structure / guidance / verbatim are not double-counted).
        report = _finalize_report(
            _dedupe_issues([*hard_issues, *rule_issues]),
            fail_on_warning=fail_on_warning,
        )
        return report.model_copy(update={"validator": "rules"})

    def _validate_with_openai(
        self,
        request: CreateTranscriptRequest,
        output: Agent1Output,
        *,
        fail_on_warning: bool,
    ) -> TranscriptValidationReport:
        validator = self._llm_validator or OpenAITranscriptValidator()
        return validator.validate(
            request,
            output,
            pattern_by_family=self._pattern_by_family,
            examples=self._examples,
            fail_on_warning=fail_on_warning,
        )

    def _validate_with_rules(
        self,
        request: CreateTranscriptRequest,
        output: Agent1Output,
    ) -> list:
        context = PatternSelectionContext(
            generation_code=request.generation_code,
            wound_id=request.wound_id,
            stage_no=request.stage_no,
            pillar_code=request.pillar_code,
            content_type=request.content_type,
        )
        plan_pairs = [(slot.slot, slot.pattern_family) for slot in output.pattern_plan.slots]
        return [
            *check_section_structure(output.sectioned_script),
            *check_pattern_plan_alignment(
                output.sectioned_script,
                pattern_by_family=self._pattern_by_family,
                plan_families=plan_pairs,
            ),
            *check_taxonomy_fit(
                context,
                pattern_by_family=self._pattern_by_family,
                plan_families=plan_pairs,
                selector=self._selector,
            ),
            *check_duration(
                request,
                duration_seconds=output.duration_estimate.seconds,
            ),
            *check_narration_hygiene(output.sectioned_script),
            *check_composer_guidance_leakage(
                output.sectioned_script,
                pattern_by_family=self._pattern_by_family,
                plan_families=plan_pairs,
            ),
            *check_invite_register(output.sectioned_script),
            *check_canonical_beats(
                output.sectioned_script,
                pattern_by_family=self._pattern_by_family,
                plan_families=plan_pairs,
            ),
            *check_verbatim_examples(
                output.transcript_text,
                self._examples,
                pattern_families={family for _, family in plan_pairs},
            ),
            *check_session_theme(request, output.sectioned_script),
            *check_relatability_pack(request, output.sectioned_script),
        ]

    def validate_or_raise(
        self,
        request: CreateTranscriptRequest,
        output: Agent1Output,
        *,
        fail_on_warning: bool = False,
    ) -> TranscriptValidationReport:
        report = self.validate(request, output, fail_on_warning=fail_on_warning)
        if not report.passed:
            raise TranscriptValidationError(
                report.format_summary(),
                report=report,
            )
        return report


def _dedupe_issues(issues: list) -> list:
    seen: set[tuple[str, str, str | None]] = set()
    out: list = []
    for issue in issues:
        key = (issue.code, issue.message, issue.slot)
        if key in seen:
            continue
        seen.add(key)
        out.append(issue)
    return out


def _merge_reports(
    hard_issues: list,
    llm_report: TranscriptValidationReport,
    *,
    fail_on_warning: bool,
) -> TranscriptValidationReport:
    issues = [*hard_issues, *llm_report.issues]
    return _finalize_report(issues, fail_on_warning=fail_on_warning)


def _downgrade_llm_errors_to_warnings(
    report: TranscriptValidationReport,
) -> TranscriptValidationReport:
    """Prevent qualitative LLM feedback from blocking compose."""
    if not report.issues:
        return report
    issues = []
    for issue in report.issues:
        if issue.severity is ValidationSeverity.ERROR:
            issues.append(issue.model_copy(update={"severity": ValidationSeverity.WARN}))
        else:
            issues.append(issue)
    error_count = 0
    warning_count = len(issues)
    return report.model_copy(
        update={
            "passed": True,
            "error_count": error_count,
            "warning_count": warning_count,
            "issues": issues,
        }
    )


def _finalize_report(issues: list, *, fail_on_warning: bool) -> TranscriptValidationReport:
    error_count = sum(1 for issue in issues if issue.severity == ValidationSeverity.ERROR)
    warning_count = sum(1 for issue in issues if issue.severity == ValidationSeverity.WARN)
    passed = error_count == 0 and (warning_count == 0 or not fail_on_warning)
    return TranscriptValidationReport(
        passed=passed,
        error_count=error_count,
        warning_count=warning_count,
        issues=issues,
    )
