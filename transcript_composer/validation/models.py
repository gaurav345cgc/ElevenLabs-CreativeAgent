"""Validation report models for Agent 1 transcript output."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARN = "warn"


class ValidationIssue(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    severity: ValidationSeverity
    message: str
    slot: str | None = None
    source: str = Field(
        default="pattern_index",
        description="pattern_index | examples | structure | llm",
    )


class TranscriptValidationReport(BaseModel):
    passed: bool
    error_count: int = 0
    warning_count: int = 0
    issues: list[ValidationIssue] = Field(default_factory=list)
    validator: str | None = Field(
        default=None,
        description="openai | rules — engine that produced this report",
    )

    def format_summary(self) -> str:
        if self.passed and not self.issues:
            engine = f" ({self.validator})" if self.validator else ""
            return f"Transcript validation passed{engine}."
        lines = [
            f"Validation: {'PASSED' if self.passed else 'FAILED'} "
            f"({self.error_count} errors, {self.warning_count} warnings)"
            + (f" — engine: {self.validator}" if self.validator else ""),
        ]
        for issue in self.issues:
            prefix = issue.severity.value.upper()
            slot = f" [{issue.slot}]" if issue.slot else ""
            lines.append(f"  {prefix}{slot}: {issue.message}")
        return "\n".join(lines)
