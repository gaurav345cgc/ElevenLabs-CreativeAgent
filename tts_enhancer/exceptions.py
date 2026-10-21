"""Agent 2 enhancement errors."""

from __future__ import annotations


class EnhancementError(Exception):
    """Base error for Agent 2 operations."""


class TransientEnhancementError(EnhancementError):
    """Safe to retry via SQS — another worker may be in progress or DB was busy."""


class EnhancementQualityError(EnhancementError):
    """Output failed quality checks — route to REVIEW_REQUIRED."""
