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
BACKGROUND_SELECTION_PROMPT_VERSION = "bg-select-v1"
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
    planner = client or OpenAIBackgroundSelectorClient()
    raw = planner.select_background(
        content_text=content_text,
        title=title,
        content_type=content_type,
        generation_code=generation_code,
        wound_id=wound_id,
        stage_no=stage_no,
        pillar_code=pillar_code,
    )
    return parse_background_selection_response(raw, model=planner.model)


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
    ) -> dict[str, Any]:
        system, user = build_selector_prompts(
            content_text=content_text,
            title=title,
            content_type=content_type,
            generation_code=generation_code,
            wound_id=wound_id,
            stage_no=stage_no,
            pillar_code=pillar_code,
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
) -> tuple[str, str]:
    catalog_lines = "\n".join(
        f"- {entry['code']}: {entry['display_name']} — {entry['mood']}"
        for entry in catalog_entries()
    )
    excerpt = (content_text or "").strip()[:_SCRIPT_EXCERPT_CHARS]
    system = f"""You choose ONE background bed from an approved meditation catalog for guided narration.

Rules:
- Pick only from the provided codes. Never invent a code.
- Bed plays quietly under a spoken meditation voice — prefer sparse pads over anything that would steal attention.
- Match emotional register and wound of the script (e.g. sanctuary/safety, earth/body, the_deep/grief, replenish/fatigue).
- Return JSON only with keys: selected_code (string), reason (one sentence), alternatives (array of 3 objects: code, reason).
- alternatives must be different from selected_code and from each other.
- prompt_version={BACKGROUND_SELECTION_PROMPT_VERSION}"""
    user = f"""Title: {title or "(untitled)"}
content_type: {content_type or "(none)"}
generation_code: {generation_code or "(none)"}
wound_id: {wound_id or "(none)"}
stage_no: {stage_no if stage_no is not None else "(none)"}
pillar_code: {pillar_code or "(none)"}

Approved catalog:
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
