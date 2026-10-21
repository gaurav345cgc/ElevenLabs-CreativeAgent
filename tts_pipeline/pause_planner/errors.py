"""Pause planner errors."""

from __future__ import annotations


class PausePlannerError(ValueError):
    """Invalid pause plan, anchors, policy, or planner configuration."""


class PausePlannerTransientError(PausePlannerError):
    """Retryable planner failure (timeout, rate limit, provider 5xx)."""


class PausePlannerValidationError(PausePlannerError):
    """Planner returned empty, non-JSON, or schema-invalid payload."""
