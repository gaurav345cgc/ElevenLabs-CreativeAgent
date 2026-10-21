"""API authentication helpers."""

from __future__ import annotations

import os
import secrets
from uuid import UUID

from fastapi import Header, HTTPException, status

from models.errors import ErrorCode, ErrorEnvelope


def resolve_api_key() -> str | None:
    value = os.environ.get("CREATIVE_AGENT_API_KEY", "").strip()
    return value or None


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Validate internal API key when CREATIVE_AGENT_API_KEY is configured."""
    expected = resolve_api_key()
    if expected is None:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorEnvelope(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="Invalid or missing API key",
            ).model_dump(mode="json"),
        )


def require_tenant_header(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> UUID:
    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorEnvelope(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="X-Tenant-Id header is required",
            ).model_dump(mode="json"),
        )
    try:
        return UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorEnvelope(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="X-Tenant-Id must be a valid UUID",
            ).model_dump(mode="json"),
        ) from exc


def assert_tenant_access(*, resource_tenant_id: UUID, caller_tenant_id: UUID) -> None:
    if resource_tenant_id != caller_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorEnvelope(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="Tenant does not have access to this transcript",
            ).model_dump(mode="json"),
        )
