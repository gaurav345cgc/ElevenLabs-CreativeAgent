"""Shared types and conventions for domain contracts (schema v1)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field

SCHEMA_VERSION = "1.0"

TranscriptId = Annotated[UUID, Field(description="Canonical transcript entity id")]
TenantId = Annotated[UUID, Field(description="Tenant that owns the transcript")]
VersionId = Annotated[UUID, Field(description="Immutable transcript version id")]
AssetId = Annotated[UUID, Field(description="Optional upstream asset reference")]


def utc_now() -> datetime:
    """Timezone-aware UTC timestamp for models and audit fields."""
    return datetime.now(UTC)


def build_enhancement_idempotency_key(
    transcript_id: UUID,
    raw_version_id: UUID,
    *,
    strategy: str = "enhancement-v1",
) -> str:
    """Stable idempotency key for Lambda 2 / SQS."""
    return f"{transcript_id}:{raw_version_id}:{strategy}"
