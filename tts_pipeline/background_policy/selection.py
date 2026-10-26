"""OpenAI picks a catalog bed for a transcript (Script Hub + TTS mix)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

from transcript_composer.llm_config import ensure_dotenv_loaded, require_openai_api_key
from tts_pipeline.background_policy.profiles import (
    DEFAULT_BACKGROUND_PROFILE_CODE,
    catalog_entries,
    display_name_for_code,
)
from tts_pipeline.background_policy.resolver import BackgroundPolicyError, get_background_profile
from tts_pipeline.persistence.s3_keys import background_track_key

logger = logging.getLogger("creative_agent.tts.background_policy")

BACKGROUND_SELECTION_KEY = "background_selection"
BACKGROUND_PROFILE_CODE_KEY = "background_profile_code"
BACKGROUND_SELECTION_PROMPT_VERSION = "bg-select-v3"
DEFAULT_SELECTOR_MODEL = "gpt-4o-mini"
DEFAULT_ALTERNATIVE_COUNT = 3
_SCRIPT_EXCERPT_CHARS = 1600

CreateCompletionFn = Callable[..., Any]


def copy_background_metadata(source: dict | None) -> dict:
    """Flatten bed choice fields for ENHANCED → APPROVED_FINAL → audio job."""
    if not isinstance(source, dict):
        return {}
    out: dict[str, Any] = {}
    code = source.get(BACKGROUND_PROFILE_CODE_KEY)
    selection = source.get(BACKGROUND_SELECTION_KEY)
    if code is not None:
        out[BACKGROUND_PROFILE_CODE_KEY] = code
    if selection is not None:
        out[BACKGROUND_SELECTION_KEY] = selection
        if code is None and isinstance(selection, dict) and selection.get("selected_code"):
            out[BACKGROUND_PROFILE_CODE_KEY] = selection["selected_code"]
    return out


def load_background_selection(metadata_json: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(metadata_json, dict):
        return None
    raw = metadata_json.get(BACKGROUND_SELECTION_KEY)
    if not isinstance(raw, dict) or not raw.get("selected_code"):
        return None
    return raw


def default_background_selection(*, alternative_count: int = DEFAULT_ALTERNATIVE_COUNT) -> dict[str, Any]:
    selected = DEFAULT_BACKGROUND_PROFILE_CODE
    alts = [
        _alt_payload(code, "Also a quiet under-voice pad from the approved catalog.")
        for code in _approved_codes()
        if code != selected
    ][:alternative_count]
    return _selection_payload(
        selected_code=selected,
        reason="Fallback catalog default until a script-specific pick is available.",
        alternatives=alts,
        selected_by="default",
        model=None,
    )


def apply_reviewer_background_choice(
    existing: dict[str, Any] | None,
    profile_code: str,
) -> dict[str, Any]:
    """Lock a catalog code as the mix bed; keep other OpenAI options as alternates."""
    get_background_profile(profile_code)
    base = dict(existing) if isinstance(existing, dict) else default_background_selection()
    previous = str(base.get("selected_code") or "")
    alts = [item for item in (base.get("alternatives") or []) if isinstance(item, dict)]
    alts = [item for item in alts if str(item.get("code") or "") not in {profile_code, ""}]
    if previous and previous != profile_code:
        alts.insert(
            0,
            _alt_payload(previous, str(base.get("reason") or "Previously suggested for this script.")),
        )
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in alts:
        code = str(item.get("code") or "")
        if code in seen or not _is_approved(code):
            continue
        seen.add(code)
        deduped.append(item)
        if len(deduped) >= DEFAULT_ALTERNATIVE_COUNT:
            break
    return _selection_payload(
        selected_code=profile_code,
        reason=f"Reviewer chose {display_name_for_code(profile_code)} for this script.",
        alternatives=deduped,
        selected_by="reviewer",
        model=base.get("model"),
        openai_reason=base.get("openai_reason"),
    )


def parse_background_selection_response(
    raw: dict[str, Any],
    *,
    model: str,
) -> dict[str, Any]:
    """Validate OpenAI JSON against the approved catalog."""
    selected = str(raw.get("selected_code") or "").strip()
    if not _is_approved(selected):
        raise BackgroundPolicyError(f"selector returned unknown profile {selected!r}")
    reason = str(raw.get("reason") or "").strip() or (
        f"{display_name_for_code(selected)} fits this script's emotional register."
    )
    alternatives_raw = raw.get("alternatives") or []
    if not isinstance(alternatives_raw, list):
        raise BackgroundPolicyError("selector 'alternatives' must be an array")

    alternatives: list[dict[str, Any]] = []
    seen = {selected}
    for item in alternatives_raw:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if not _is_approved(code) or code in seen:
            continue
        seen.add(code)
        alt_reason = str(item.get("reason") or "").strip() or "Close catalog neighbour."
        alternatives.append(_alt_payload(code, alt_reason))
        if len(alternatives) >= DEFAULT_ALTERNATIVE_COUNT:
            break

    for code in _approved_codes():
        if len(alternatives) >= DEFAULT_ALTERNATIVE_COUNT:
            break
        if code in seen:
            continue
        alternatives.append(_alt_payload(code, "Also available from the approved catalog."))
        seen.add(code)

    return _selection_payload(
        selected_code=selected,
        reason=reason,
        alternatives=alternatives,
        selected_by="openai",
        model=model,
        openai_reason=reason,
    )


def create_background_selection(
    *,
    content_text: str,
    title: str | None = None,
    content_type: str | None = None,
    generation_code: str | None = None,
    wound_id: str | None = None,
    stage_no: int | None = None,
    pillar_code: str | None = None,
    client: OpenAIBackgroundSelectorClient | None = None,
) -> dict[str, Any]:
    from tts_pipeline.background_policy.affinity import affinity_for_brief, apply_affinity_rail

    planner = client or OpenAIBackgroundSelectorClient()
    rail = affinity_for_brief(pillar_code=pillar_code, wound_id=wound_id)
    raw = planner.select_background(
        content_text=content_text,
        title=title,
        content_type=content_type,
        generation_code=generation_code,
        wound_id=wound_id,
        stage_no=stage_no,
        pillar_code=pillar_code,
        preferred_codes=rail.get("preferred") or [],
        avoid_codes=rail.get("avoid") or [],
    )
    parsed = parse_background_selection_response(raw, model=planner.model)
    final_code, rail_note = apply_affinity_rail(
        str(parsed["selected_code"]),
        pillar_code=pillar_code,
        wound_id=wound_id,
    )
    if final_code != parsed["selected_code"]:
        # Snap to rail — keep original pick as first alternative.
        previous = str(parsed["selected_code"])
        alts = [
            _alt_payload(previous, str(parsed.get("reason") or "OpenAI pick before affinity rail.")),
            *[
                item
                for item in (parsed.get("alternatives") or [])
                if isinstance(item, dict) and str(item.get("code") or "") not in {final_code, previous, ""}
            ],
        ][:DEFAULT_ALTERNATIVE_COUNT]
        parsed = _selection_payload(
            selected_code=final_code,
            reason=(
                f"{parsed.get('reason') or ''} "
                f"[affinity rail → {final_code}]"
            ).strip(),
            alternatives=alts,
            selected_by="openai_affinity_rail",
            model=planner.model,
            openai_reason=parsed.get("openai_reason") or parsed.get("reason"),
        )
    parsed["affinity"] = {
        "preferred": rail.get("preferred") or [],
        "avoid": rail.get("avoid") or [],
        "rail_note": rail_note,
    }
    return parsed


def resolve_bg_selector_mode() -> str:
    """auto | openai | off — how we pick a catalog bed for a script."""
    ensure_dotenv_loaded()
    return (
        os.environ.get("CREATIVE_AGENT_BG_SELECTOR", "auto").strip().lower() or "auto"
    )


def select_background_for_script(
    *,
    content_text: str,
    title: str | None = None,
    content_type: str | None = None,
    generation_code: str | None = None,
    wound_id: str | None = None,
    stage_no: int | None = None,
    pillar_code: str | None = None,
    client: OpenAIBackgroundSelectorClient | None = None,
) -> dict[str, Any]:
    """Pick a catalog bed from script + taxonomy via OpenAI; fall back to default.

    ``CREATIVE_AGENT_BG_SELECTOR``:
    - ``auto`` (default): OpenAI when a key is available, else catalog default
    - ``openai``: require OpenAI (still falls back to default on selector errors)
    - ``off``: always catalog default (``calm_ambient_01``)
    """
    mode = resolve_bg_selector_mode()
    if mode in {"off", "default", "false", "0"}:
        return default_background_selection()

    use_openai = mode in {"auto", "openai", "on", "true", "1"}
    if mode == "auto":
        try:
            from transcript_composer.llm_config import resolve_openai_api_key

            use_openai = bool(resolve_openai_api_key())
        except Exception:
            use_openai = False

    if not use_openai:
        return default_background_selection()

    try:
        return create_background_selection(
            content_text=content_text,
            title=title,
            content_type=content_type,
            generation_code=generation_code,
            wound_id=wound_id,
            stage_no=stage_no,
            pillar_code=pillar_code,
            client=client,
        )
    except Exception as exc:
        logger.warning(
            "background OpenAI selector failed; using catalog default: %s",
            exc,
        )
        return default_background_selection()


class OpenAIBackgroundSelectorClient:
    """Pick one approved bed plus closest alternatives from script + taxonomy."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        model: str | None = None,
        api_key: str | None = None,
        create_completion: CreateCompletionFn | None = None,
        temperature: float = 0.2,
        timeout_seconds: float = 30.0,
    ) -> None:
        ensure_dotenv_loaded()
        self._model = model or _resolve_selector_model()
        self._temperature = temperature
        self._timeout_seconds = timeout_seconds
        if create_completion is not None:
            self._create_completion = create_completion
        else:
            built = client or _build_openai_client(api_key or require_openai_api_key())
            self._create_completion = built.chat.completions.create

    @property
    def model(self) -> str:
        return self._model

    def select_background(
        self,
        *,
        content_text: str,
        title: str | None = None,
        content_type: str | None = None,
        generation_code: str | None = None,
        wound_id: str | None = None,
        stage_no: int | None = None,
        pillar_code: str | None = None,
        preferred_codes: list[str] | None = None,
        avoid_codes: list[str] | None = None,
    ) -> dict[str, Any]:
        system, user = build_selector_prompts(
            content_text=content_text,
            title=title,
            content_type=content_type,
            generation_code=generation_code,
            wound_id=wound_id,
            stage_no=stage_no,
            pillar_code=pillar_code,
            preferred_codes=preferred_codes,
            avoid_codes=avoid_codes,
        )
        response = self._create_completion(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self._temperature,
            response_format={"type": "json_object"},
            timeout=self._timeout_seconds,
        )
        content = _message_content(response)
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise BackgroundPolicyError(f"background selector returned non-JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise BackgroundPolicyError("background selector JSON root must be an object")
        return payload


def build_selector_prompts(
    *,
    content_text: str,
    title: str | None,
    content_type: str | None,
    generation_code: str | None,
    wound_id: str | None,
    stage_no: int | None,
    pillar_code: str | None,
    preferred_codes: list[str] | None = None,
    avoid_codes: list[str] | None = None,
) -> tuple[str, str]:
    catalog_lines = "\n".join(
        f"- {entry['code']}: {entry['display_name']} — "
        f"{entry.get('listen_summary') or entry['mood']}"
        for entry in catalog_entries()
    )
    excerpt = (content_text or "").strip()[:_SCRIPT_EXCERPT_CHARS]
    try:
        from transcript_composer.theme import generation_label, pillar_label, wound_label

        wound_name = wound_label(wound_id)
        pillar_name = pillar_label(pillar_code) or "(none)"
        generation_name = generation_label(generation_code)
    except Exception:
        wound_name = wound_id or "(none)"
        pillar_name = pillar_code or "(none)"
        generation_name = generation_code or "(none)"

    preferred = [c for c in (preferred_codes or []) if c]
    avoid = [c for c in (avoid_codes or []) if c]
    preferred_block = (
        ", ".join(preferred)
        if preferred
        else "(none — use listen notes + script)"
    )
    avoid_block = ", ".join(avoid) if avoid else "(none)"

    system = f"""You choose ONE background bed from an approved meditation catalog for guided narration.

Rules:
- Pick only from the provided codes. Never invent a code.
- STRONGLY prefer the PREFERRED list for this wound/pillar (ranked best→ok). Only leave it if the script clearly conflicts.
- Never pick a code from AVOID unless preferred is empty.
- Catalog lines include concrete LISTEN + LOUDNESS notes — trust measured loudness and brightness/pulse over the display name.
- Bed must sit quietly under spoken guidance (under_voice_risk no/maybe only).
- Match wound + pillar labels AND script tone.
- Return JSON only with keys: selected_code (string), reason (one sentence), alternatives (array of 3 objects: code, reason).
- alternatives must be different from selected_code and from each other; prefer other PREFERRED codes as alternatives.
- prompt_version={BACKGROUND_SELECTION_PROMPT_VERSION}"""
    user = f"""Title: {title or "(untitled)"}
content_type: {content_type or "(none)"}
generation: {generation_code or "(none)"} ({generation_name})
wound: {wound_id or "(none)"} ({wound_name})
stage_no: {stage_no if stage_no is not None else "(none)"}
pillar: {pillar_code or "(none)"} ({pillar_name})

PREFERRED beds for this wound/pillar (best first): {preferred_block}
AVOID beds for this wound/pillar: {avoid_block}

Approved catalog (concrete listen + loudness notes):
{catalog_lines}

Script excerpt:
{excerpt or "(empty)"}"""
    return system, user


def _selection_payload(
    *,
    selected_code: str,
    reason: str,
    alternatives: list[dict[str, Any]],
    selected_by: str,
    model: str | None,
    openai_reason: str | None = None,
) -> dict[str, Any]:
    payload = {
        "selected_code": selected_code,
        "selected_display_name": display_name_for_code(selected_code),
        "reason": reason,
        "alternatives": alternatives,
        "selected_by": selected_by,
        "prompt_version": BACKGROUND_SELECTION_PROMPT_VERSION,
        "track_object_key": background_track_key(selected_code),
        BACKGROUND_PROFILE_CODE_KEY: selected_code,
    }
    if model:
        payload["model"] = model
    if openai_reason:
        payload["openai_reason"] = openai_reason
    return payload


def _alt_payload(code: str, reason: str) -> dict[str, Any]:
    return {
        "code": code,
        "display_name": display_name_for_code(code),
        "reason": reason,
        "track_object_key": background_track_key(code),
    }


def _approved_codes() -> list[str]:
    return [entry["code"] for entry in catalog_entries()]


def _is_approved(code: str) -> bool:
    if not code:
        return False
    try:
        get_background_profile(code)
        return True
    except BackgroundPolicyError:
        return False


def _resolve_selector_model() -> str:
    ensure_dotenv_loaded()
    return (
        os.environ.get("CREATIVE_AGENT_BG_SELECTOR_MODEL", "").strip()
        or os.environ.get("CREATIVE_AGENT_OPENAI_MODEL", "").strip()
        or DEFAULT_SELECTOR_MODEL
    )


def _build_openai_client(api_key: str) -> Any:
    from openai import OpenAI

    return OpenAI(api_key=api_key)


def _message_content(response: Any) -> str:
    try:
        return response.choices[0].message.content or ""
    except (AttributeError, IndexError, KeyError):
        return ""
