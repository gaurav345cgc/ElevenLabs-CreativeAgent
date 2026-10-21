"""Resolve approved background profiles for post-TTS bed mixing."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from tts_pipeline.background_policy.profiles import (
    APPROVED_BACKGROUND_PROFILES,
    DEFAULT_BACKGROUND_PROFILE_CODE,
)
from tts_pipeline.background_policy.schema import BackgroundProfile

logger = logging.getLogger("creative_agent.tts.background_policy")


class BackgroundPolicyError(ValueError):
    """Raised when a caller requests disallowed background configuration."""


def list_background_profile_codes() -> list[str]:
    return sorted(APPROVED_BACKGROUND_PROFILES)


def get_background_profile(code: str) -> BackgroundProfile:
    profile = APPROVED_BACKGROUND_PROFILES.get(code)
    if profile is None:
        known = ", ".join(list_background_profile_codes()) or "(none)"
        raise BackgroundPolicyError(f"Unknown background profile {code!r}. Approved profiles: {known}")
    return profile


def resolve_background_profile(
    *,
    content_type: str | None = None,
    tenant_id: UUID | None = None,
    requested_code: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> BackgroundProfile:
    """Return the approved bed for this job.

    Preference: explicit ``requested_code`` → stored ``background_profile_code`` /
    ``background_selection.selected_code`` on job or version metadata → default.
    Unknown codes fall back to the default catalog bed (never invent a track).
    """
    _ = content_type, tenant_id
    for candidate in (requested_code, *background_code_candidates(metadata_json)):
        if not candidate:
            continue
        try:
            return get_background_profile(str(candidate))
        except BackgroundPolicyError:
            logger.warning("ignoring unknown background profile %r; trying next", candidate)
    return get_background_profile(DEFAULT_BACKGROUND_PROFILE_CODE)


def background_code_candidates(metadata_json: dict[str, Any] | None) -> list[str]:
    if not isinstance(metadata_json, dict):
        return []
    codes: list[str] = []
    for mapping in _metadata_layers(metadata_json):
        raw = mapping.get("background_profile_code")
        if raw:
            codes.append(str(raw))
        selection = mapping.get("background_selection")
        if isinstance(selection, dict) and selection.get("selected_code"):
            codes.append(str(selection["selected_code"]))
    return codes


def _metadata_layers(metadata_json: dict[str, Any]) -> list[dict[str, Any]]:
    layers: list[dict[str, Any]] = [metadata_json]
    trace = metadata_json.get("traceability")
    if isinstance(trace, dict):
        tv = trace.get("transcript_version")
        if isinstance(tv, dict):
            nested = tv.get("metadata_json")
            if isinstance(nested, dict):
                layers.append(nested)
    return layers
