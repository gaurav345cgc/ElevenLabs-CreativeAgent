"""Grounded pain + pillar QA judge (post-compose).

Anti-hallucination controls:
- Criteria text comes ONLY from the First-10 relatability pack (never invented).
- Temperature 0 + constrained JSON schema with a fixed issue-code whitelist.
- Every ERROR must include an evidence_quote that is an exact substring of the script;
  unverified quotes are dropped (not treated as failures).
- Low scores alone never fail without verified evidence.
- API / infra failures become WARN only (do not block compose).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from models.agents import Agent1Output
from models.requests import CreateTranscriptRequest
from transcript_composer.llm_config import (
    resolve_openai_api_key,
    resolve_openai_model,
    resolve_pain_pillar_qa_mode,
    require_openai_api_key,
)
from transcript_composer.validation.models import ValidationIssue, ValidationSeverity

logger = logging.getLogger("creative_agent.composer.pain_pillar_qa")

ALLOWED_ISSUE_CODES = frozenset(
    {
        "pain_pillar_wound_weak",
        "pain_pillar_pillar_mismatch",
        "pain_pillar_better_match",
        "pain_pillar_generic",
        "pain_pillar_mind_heart_miss",
    }
)

SYSTEM_PROMPT = """\
You are a grounded QA judge for meditation narration scripts.

Hard rules (never violate):
1. Use ONLY the CRITERIA block below. Do not invent wound stories, pillars, or rival definitions.
2. Judge whether the SCRIPT specifically lands THIS wound and THIS pillar.
3. Every issue with severity "error" MUST include evidence_quote: an exact contiguous
   substring copied from the SCRIPT (not paraphrased, not invented).
4. If you cannot quote exact script text, do not emit that issue.
5. Prefer pass when the script is specific enough; only fail on clear mismatch or generic calm.
6. Never mention product codes, wound_ids, or pillar codes as if the listener should hear them.
"""

_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "pain_pillar_qa",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "passed": {"type": "boolean"},
                "wound_score": {"type": "number"},
                "pillar_score": {"type": "number"},
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "code": {
                                "type": "string",
                                "enum": sorted(ALLOWED_ISSUE_CODES),
                            },
                            "severity": {
                                "type": "string",
                                "enum": ["error", "warn"],
                            },
                            "message": {"type": "string"},
                            "slot": {
                                "type": "string",
                                "description": "composition slot or empty string if N/A",
                            },
                            "evidence_quote": {"type": "string"},
                        },
                        "required": [
                            "code",
                            "severity",
                            "message",
                            "slot",
                            "evidence_quote",
                        ],
                    },
                },
            },
            "required": ["passed", "wound_score", "pillar_score", "issues"],
        },
    },
}


class _LlmIssue(BaseModel):
    code: str
    severity: Literal["error", "warn"] = "error"
    message: str
    slot: str = ""
    evidence_quote: str = ""


class _LlmPayload(BaseModel):
    passed: bool = True
    wound_score: float = Field(default=1.0, ge=0.0, le=1.0)
    pillar_score: float = Field(default=1.0, ge=0.0, le=1.0)
    issues: list[_LlmIssue] = Field(default_factory=list)


def pain_pillar_qa_enabled() -> bool:
    mode = resolve_pain_pillar_qa_mode()
    if mode in {"off", "false", "0", "no"}:
        return False
    if mode in {"on", "true", "1", "yes"}:
        return True
    # auto
    return bool(resolve_openai_api_key())


def _normalize_evidence(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def evidence_quote_in_script(quote: str, script: str, *, min_chars: int = 12) -> bool:
    """True when quote is a real contiguous substring of the script (anti-hallucination)."""
    q = _normalize_evidence(quote)
    if len(q) < min_chars:
        return False
    return q in _normalize_evidence(script)


def _rival_briefs(fail_codes: list[str], *, exclude: str) -> list[dict[str, str]]:
    from transcript_composer.relatability import entry_by_product_code

    rivals: list[dict[str, str]] = []
    for code in fail_codes:
        entry = entry_by_product_code(str(code))
        if entry is None:
            continue
        product = str(entry.get("product_code") or code).upper()
        if product == exclude.upper():
            continue
        brief = entry.get("brief") or {}
        rivals.append(
            {
                "product_code": product,
                "display_name": str(entry.get("display_name") or ""),
                "wound_story": str(brief.get("wound_story") or "")[:400],
                "required_life_domain": str(brief.get("required_life_domain") or ""),
            }
        )
    return rivals


def _build_criteria_and_script(
    request: CreateTranscriptRequest,
    output: Agent1Output,
) -> tuple[dict[str, Any], str] | None:
    from transcript_composer.relatability import (
        load_relatability_pack,
        resolve_relatability_entry,
    )

    entry = resolve_relatability_entry(request)
    if entry is None:
        return None

    brief = entry.get("brief") or {}
    product = str(entry.get("product_code") or "?")
    pillar = str(entry.get("pillar_code") or request.pillar_code or "")
    pack = load_relatability_pack()
    pillar_kit = (pack.get("pillars") or {}).get(pillar.lower(), {})
    validator = entry.get("validator") or {}
    rivals = _rival_briefs(
        list(validator.get("fail_if_better_matches") or []),
        exclude=product,
    )

    criteria = {
        "product_code": product,
        "display_name": entry.get("display_name"),
        "generation_code": entry.get("generation_code") or request.generation_code,
        "pillar_code": pillar,
        "required_life_domain": brief.get("required_life_domain"),
        "listener_portrait": brief.get("listener_portrait"),
        "wound_story": brief.get("wound_story"),
        "pillar_feel": brief.get("pillar_feel"),
        "opening_job": brief.get("opening_job"),
        "mind_heart_core": brief.get("mind_heart_core"),
        "closing_promise": brief.get("closing_promise"),
        "must_use_phrases": list(brief.get("must_use_phrases") or [])[:16],
        "must_not_say": list(brief.get("must_not_say") or [])[:12],
        "anti_generic_traps": brief.get("anti_generic_traps"),
        "pillar_invite_phrases": list(pillar_kit.get("invite_phrases") or [])[:6],
        "pillar_violating_phrases": list(pillar_kit.get("violating_phrases") or [])[:5],
        "fail_if_better_matches": rivals,
    }
    script = "\n\n".join(
        f"## [{section.slot}]\n{section.text}" for section in output.sectioned_script.sections
    )
    return criteria, script


def _ground_issues(payload: _LlmPayload, script: str) -> list[ValidationIssue]:
    """Keep only whitelist codes with verified evidence for ERRORs."""
    issues: list[ValidationIssue] = []
    for item in payload.issues:
        if item.code not in ALLOWED_ISSUE_CODES:
            logger.warning("pain_pillar_qa dropped unknown code %s", item.code)
            continue
        severity = (
            ValidationSeverity.ERROR
            if item.severity == "error"
            else ValidationSeverity.WARN
        )
        if severity is ValidationSeverity.ERROR:
            if not evidence_quote_in_script(item.evidence_quote, script):
                logger.warning(
                    "pain_pillar_qa dropped unverified error %s (no evidence in script)",
                    item.code,
                )
                continue
            message = (
                f"{item.message} (evidence: {item.evidence_quote.strip()[:120]})"
            )
        else:
            # WARN may omit evidence; still prefer verified when present.
            message = item.message
            if item.evidence_quote and evidence_quote_in_script(
                item.evidence_quote, script, min_chars=8
            ):
                message = f"{item.message} (evidence: {item.evidence_quote.strip()[:120]})"

        slot = (item.slot or "").strip() or None
        if slot and slot not in {
            "opening",
            "settling",
            "body",
            "breath",
            "mind_heart",
            "closing",
        }:
            slot = None
        issues.append(
            ValidationIssue(
                code=item.code,
                severity=severity,
                message=message,
                slot=slot,
                source="pain_pillar_qa",
            )
        )
    return issues


class PainPillarAgent:
    """OpenAI-backed pain+pillar judge with pack grounding + evidence verification."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._model = model or resolve_openai_model()
        self._client = client or self._build_client(api_key or require_openai_api_key())

    def judge(
        self,
        request: CreateTranscriptRequest,
        output: Agent1Output,
    ) -> list[ValidationIssue]:
        built = _build_criteria_and_script(request, output)
        if built is None:
            return []
        criteria, script = built
        user_prompt = (
            "CRITERIA (authoritative — use only this):\n"
            f"{json.dumps(criteria, ensure_ascii=True, indent=2)}\n\n"
            "SCRIPT:\n"
            f"{script}\n\n"
            "Return JSON matching the schema. "
            "ERROR issues require evidence_quote copied exactly from SCRIPT."
        )
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                response_format=_RESPONSE_SCHEMA,
            )
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("OpenAI returned empty pain_pillar_qa response")
            payload = _LlmPayload.model_validate(json.loads(content))
        except Exception as exc:  # noqa: BLE001 — infra must not block compose
            logger.warning("pain_pillar_qa skipped due to error: %s", exc)
            return [
                ValidationIssue(
                    code="pain_pillar_qa_unavailable",
                    severity=ValidationSeverity.WARN,
                    message=f"pain+pillar QA unavailable: {exc}",
                    source="pain_pillar_qa",
                )
            ]

        return _ground_issues(payload, script)

    @staticmethod
    def _build_client(api_key: str) -> Any:
        from openai import OpenAI

        return OpenAI(api_key=api_key)


def run_pain_pillar_qa(
    request: CreateTranscriptRequest,
    output: Agent1Output,
    *,
    agent: PainPillarAgent | None = None,
) -> list[ValidationIssue]:
    """Entry point used by TranscriptValidator. No-op when disabled or no pack entry.

    An injected ``agent`` always runs (for tests / DI); otherwise respect
    ``CREATIVE_AGENT_PAIN_PILLAR_QA``.
    """
    if agent is None and not pain_pillar_qa_enabled():
        return []
    from transcript_composer.relatability import resolve_relatability_entry

    if resolve_relatability_entry(request) is None:
        return []
    judge = agent or PainPillarAgent()
    return judge.judge(request, output)
