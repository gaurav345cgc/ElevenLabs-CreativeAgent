"""Structured API and worker error envelopes."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from models.common import SCHEMA_VERSION


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    TRANSCRIPT_STATE_ERROR = "TRANSCRIPT_STATE_ERROR"
    ENHANCEMENT_FAILED = "ENHANCEMENT_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorEnvelope(BaseModel):
    """Consistent error response for API and internal tooling."""

    schema_version: str = SCHEMA_VERSION
    error_code: ErrorCode
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None
    request_id: str | None = None
