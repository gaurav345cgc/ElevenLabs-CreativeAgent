"""Pillar/wound → preferred bed rails for background selection."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from tts_pipeline.background_policy.profiles import APPROVED_BACKGROUND_PROFILES
from tts_pipeline.background_policy.resolver import get_background_profile

_AFFINITY_PATH = Path(__file__).resolve().parents[1] / "data" / "background_pillar_affinity.json"


@lru_cache(maxsize=1)
def _affinity_payload() -> dict[str, Any]:
    if not _AFFINITY_PATH.exists():
        return {"pillars": {}, "wounds": {}}
    try:
        raw = json.loads(_AFFINITY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"pillars": {}, "wounds": {}}
    return raw if isinstance(raw, dict) else {"pillars": {}, "wounds": {}}


def _clean_codes(codes: list[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in codes or []:
        code = str(raw or "").strip()
        if not code or code in seen or code not in APPROVED_BACKGROUND_PROFILES:
            continue
        seen.add(code)
        out.append(code)
    return out


def affinity_for_brief(
    *,
    pillar_code: str | None = None,
    wound_id: str | None = None,
) -> dict[str, Any]:
    """Merge wound + pillar rails. Wound preferred comes first, then pillar."""
    payload = _affinity_payload()
    pillars = payload.get("pillars") if isinstance(payload.get("pillars"), dict) else {}
    wounds = payload.get("wounds") if isinstance(payload.get("wounds"), dict) else {}

    pillar_key = (pillar_code or "").strip().lower()
    wound_key = (wound_id or "").strip().lower()
    pillar = pillars.get(pillar_key) if isinstance(pillars.get(pillar_key), dict) else {}
    wound = wounds.get(wound_key) if isinstance(wounds.get(wound_key), dict) else {}

    preferred = _clean_codes(
        list(wound.get("preferred") or []) + list(pillar.get("preferred") or [])
    )
    avoid = set(_clean_codes(list(wound.get("avoid") or []) + list(pillar.get("avoid") or [])))
    # Never avoid something we also preferred.
    avoid -= set(preferred)

    return {
        "pillar_code": pillar_key or None,
        "pillar_label": pillar.get("label"),
        "wound_id": wound_key or None,
        "wound_label": wound.get("label"),
        "preferred": preferred,
        "avoid": sorted(avoid),
    }


def apply_affinity_rail(
    selected_code: str,
    *,
    pillar_code: str | None,
    wound_id: str | None,
) -> tuple[str, str | None]:
    """Keep OpenAI pick when compatible; otherwise snap to top preferred bed.

    Returns ``(final_code, rail_note_or_none)``.
    """
    get_background_profile(selected_code)
    rail = affinity_for_brief(pillar_code=pillar_code, wound_id=wound_id)
    preferred: list[str] = rail["preferred"]
    avoid: set[str] = set(rail["avoid"])

    if selected_code in preferred:
        return selected_code, None

    if selected_code in avoid and preferred:
        snapped = preferred[0]
        return (
            snapped,
            f"rail: replaced avoided bed {selected_code!r} with preferred {snapped!r} "
            f"for wound={rail.get('wound_id')} pillar={rail.get('pillar_code')}",
        )

    if preferred and selected_code not in preferred:
        # Soft miss: keep OpenAI creativity when not explicitly avoided.
        return (
            selected_code,
            f"rail: kept {selected_code!r} outside preferred set {preferred[:5]}",
        )

    return selected_code, None
