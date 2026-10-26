"""First-10 thin-wound relatability pack — prompt blocks + validator seeds."""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from models.requests import CreateTranscriptRequest

logger = logging.getLogger("creative_agent.composer.relatability")

DATA_PATH = Path(__file__).resolve().parent / "data" / "first10_relatability_pack.json"

_PRODUCT_CODE_RE = re.compile(
    r"\b(WK-\d{2}|PH-\d{2}|BO-\d{2}|GX-\d{2}|GZ-\d{2}|ML-\d{2}|FR)\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def load_relatability_pack() -> dict[str, Any]:
    if not DATA_PATH.exists():
        return {"schema_version": "0", "codes": [], "pillars": {}, "generations": {}}
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _codes_by_product() -> dict[str, dict[str, Any]]:
    pack = load_relatability_pack()
    return {
        str(entry["product_code"]).upper(): entry
        for entry in pack.get("codes", [])
        if entry.get("product_code")
    }


def entry_by_product_code(product_code: str) -> dict[str, Any] | None:
    """Lookup a First-10 pack entry by product code (e.g. WK-06, FR)."""
    code = (product_code or "").strip().upper()
    if not code:
        return None
    if code.startswith("FR") and code != "FR":
        code = "FR"
    return _codes_by_product().get(code)


def _codes_by_wound() -> dict[str, dict[str, Any]]:
    by_wound: dict[str, dict[str, Any]] = {}
    for entry in _codes_by_product().values():
        preferred = (entry.get("wound_id_preferred") or "").strip().lower()
        proxy = (entry.get("wound_id_fallback_proxy") or "").strip().lower()
        if preferred:
            by_wound.setdefault(preferred, entry)
        if proxy:
            by_wound.setdefault(proxy, entry)
    return by_wound


def extract_product_code_from_title(title: str | None) -> str | None:
    if not title:
        return None
    match = _PRODUCT_CODE_RE.search(title)
    if not match:
        return None
    code = match.group(1).upper()
    if code.startswith("FR"):
        return "FR"
    return code


def resolve_relatability_entry(
    request: CreateTranscriptRequest,
) -> dict[str, Any] | None:
    """Map a compose request to a First-10 pack entry, if any."""
    by_product = _codes_by_product()
    title = (request.title_hint or "").strip()
    code = extract_product_code_from_title(title)
    if code and code in by_product:
        return by_product[code]

    wound = (request.wound_id or "").strip().lower()
    by_wound = _codes_by_wound()
    if wound in by_wound:
        return by_wound[wound]
    return None


def _wound_in_pattern_index(wound_id: str) -> bool:
    """True when at least one pattern row is tagged with this wound_id."""
    from transcript_composer.knowledge.loader import get_pattern_index

    wound = wound_id.strip().lower()
    if not wound:
        return False
    return any(wound in pattern.wound_ids for pattern in get_pattern_index().patterns)


def compose_wound_id_for_entry(entry: dict[str, Any]) -> str:
    """Pattern-index wound to send on compose (preferred if indexed, else proxy)."""
    preferred = (entry.get("wound_id_preferred") or "").strip().lower()
    proxy = (entry.get("wound_id_fallback_proxy") or "").strip().lower()
    if preferred and _wound_in_pattern_index(preferred):
        return preferred
    if proxy:
        if preferred and preferred != proxy:
            logger.warning(
                "overlay wound %s not in pattern index; falling back to proxy %s",
                preferred,
                proxy,
            )
        return proxy
    return preferred or "ml_02"


def format_relatability_block(request: CreateTranscriptRequest) -> str:
    """Prompt block injected into Agent 1 section generation."""
    entry = resolve_relatability_entry(request)
    if entry is None:
        return ""

    brief = entry.get("brief") or {}
    product = entry.get("product_code", "?")
    display = entry.get("display_name", "")
    pillar = entry.get("pillar_code", "")
    gen = entry.get("generation_code", "")
    domain = brief.get("required_life_domain", "")
    must_use = brief.get("must_use_phrases") or []
    must_not = brief.get("must_not_say") or []
    portrait = (brief.get("listener_portrait") or "").strip()
    wound_story = (brief.get("wound_story") or "").strip()
    pillar_feel = (brief.get("pillar_feel") or "").strip()
    opening_job = (brief.get("opening_job") or "").strip()
    mind_heart = (brief.get("mind_heart_core") or "").strip()
    closing = (brief.get("closing_promise") or "").strip()
    gold = (brief.get("gold_opening_example") or "").strip()
    traps = (brief.get("anti_generic_traps") or "").strip()

    must_use_lines = "\n".join(f"  - {p}" for p in must_use[:16]) or "  - (none listed)"
    must_not_lines = "\n".join(f"  - {p}" for p in must_not[:12]) or "  - (none listed)"

    pack = load_relatability_pack()
    pillar_kit = (pack.get("pillars") or {}).get(str(pillar).lower(), {})
    gen_kit = (pack.get("generations") or {}).get(str(gen).lower(), {})
    invite = pillar_kit.get("invite_phrases") or []
    violate = pillar_kit.get("violating_phrases") or []
    gen_dos = gen_kit.get("dos") or []
    gen_donts = gen_kit.get("donts") or []

    parts = [
        f"## Relatability brief (product {product} — {display})",
        "This session must feel written FOR this exact wound, generation, pillar, and life situation.",
        "Never speak product codes, wound_ids, or pillar codes aloud.",
        f"- Required life domain: {domain}",
        f"- Pillar code (internal): {pillar} — speak the feel, not the code",
        f"- Generation register (internal): {gen}",
    ]
    if portrait:
        parts.append(f"\n### Listener portrait\n{portrait}")
    if wound_story:
        parts.append(f"\n### Wound story (felt sense)\n{wound_story}")
    if pillar_feel:
        parts.append(f"\n### Pillar feel\n{pillar_feel}")
    if opening_job:
        parts.append(f"\n### Opening job\n{opening_job}")
    parts.append(f"\n### Must-use phrases (weave naturally; paraphrase lightly OK)\n{must_use_lines}")
    parts.append(f"\n### Must-not-say / avoid\n{must_not_lines}")
    if mind_heart:
        parts.append(
            f"\n### Mind/heart core reframe (preserve this logical turn in mind_heart)\n{mind_heart}"
        )
    if closing:
        parts.append(f"\n### Closing promise (tone target)\n{closing}")
    if gold:
        parts.append(
            f"\n### Gold opening example (tone/scene only — do NOT copy verbatim)\n{gold}"
        )
    if traps:
        parts.append(f"\n### Anti-generic traps\n{traps}")
    if invite:
        parts.append(
            "\n### Pillar invite register (prefer)\n"
            + "\n".join(f"  - {p}" for p in invite[:6])
        )
    if violate:
        parts.append(
            "\n### Pillar violating phrases (never)\n"
            + "\n".join(f"  - {p}" for p in violate[:5])
        )
    if gen_dos or gen_donts:
        parts.append("\n### Generation register")
        if gen_dos:
            parts.append("Do:\n" + "\n".join(f"  - {p}" for p in gen_dos[:5]))
        if gen_donts:
            parts.append("Don't:\n" + "\n".join(f"  - {p}" for p in gen_donts[:5]))
    parts.append(
        "\nHard relatability requirements:\n"
        "1. OPENING must land in this wound's specific scene — not generic calm.\n"
        "2. mind_heart must deliver the mind_heart_core distinction (paraphrase OK).\n"
        "3. closing must echo the closing promise tone for THIS wound.\n"
        "4. Prefer several must-use phrases (or close paraphrases) across the script.\n"
        "5. A script that could also pass as a different First-10 wound is a failure."
    )
    return "\n".join(parts)


def relatability_validator_spec(
    request: CreateTranscriptRequest,
) -> dict[str, Any] | None:
    entry = resolve_relatability_entry(request)
    if entry is None:
        return None
    spec = dict(entry.get("validator") or {})
    spec["product_code"] = entry.get("product_code")
    brief = entry.get("brief") or {}
    # Soft boost: treat must_use tokens as additional required hits when groups miss.
    spec["_must_use_phrases"] = list(brief.get("must_use_phrases") or [])
    return spec
