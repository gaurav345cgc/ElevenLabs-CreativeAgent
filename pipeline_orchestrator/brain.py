"""OpenAI Orchestrator Brain — decides the next pipeline tool call.

Anti-hallucination rails:
- Actions are a fixed whitelist (executor rejects anything else).
- Observation is factual state + last tool result only (no invented IDs).
- Temperature 0 + strict JSON schema.
- Cannot change wound/pillar/product; cannot skip QA to TTS.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger("creative_agent.orchestrator.brain")

OrchestratorAction = Literal[
    "compose",
    "repair_and_compose",
    "enhance",
    "tts",
    "download",
    "complete",
    "fail",
]

ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {
        "compose",
        "repair_and_compose",
        "enhance",
        "tts",
        "download",
        "complete",
        "fail",
    }
)

SYSTEM_PROMPT = """\
You are the Creative Agent Orchestrator Brain.

Goal: take a meditation job from brief to final MP3 (or fail clearly).

You choose ONE next action. Tools actually run the work; you only decide.

Hard rules:
1. Never invent transcript_id, audio_job_id, or statuses — use OBSERVATION only.
2. Never change wound_id, pillar_code, generation_code, or product code.
3. Never send TTS before enhancement succeeded (status ENHANCED or APPROVED).
4. After compose QA failure (qa_report present), prefer repair_and_compose (not blind compose).
5. If repair budget exhausted or quota blocked, action=fail with a clear fail_message.
6. If skip_tts and transcript is ENHANCED/APPROVED, action=complete.
7. If final MP3 is already downloaded, action=complete.
8. Keep composer_instructions short, concrete, and tied to listed QA codes when repairing.
"""

_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "orchestrator_decision",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "thought": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": sorted(ALLOWED_ACTIONS),
                },
                "reason": {"type": "string"},
                "composer_instructions": {"type": "string"},
                "fail_message": {"type": "string"},
            },
            "required": [
                "thought",
                "action",
                "reason",
                "composer_instructions",
                "fail_message",
            ],
        },
    },
}


class BrainDecision(BaseModel):
    thought: str = ""
    action: str
    reason: str = ""
    composer_instructions: str = ""
    fail_message: str = ""

    def normalized(self) -> BrainDecision:
        action = (self.action or "").strip().lower()
        if action not in ALLOWED_ACTIONS:
            return BrainDecision(
                thought=self.thought,
                action="fail",
                reason=f"invalid action {self.action!r}; refusing",
                composer_instructions="",
                fail_message=f"Orchestrator brain returned invalid action {self.action!r}",
            )
        return self


def build_observation(state: dict[str, Any]) -> dict[str, Any]:
    """Compact factual snapshot for the brain (no large script blobs)."""
    brief = state.get("compose_brief") or {}
    qa = state.get("qa_report")
    issues = []
    if isinstance(qa, dict):
        for item in (qa.get("issues") or [])[:10]:
            if not isinstance(item, dict):
                continue
            issues.append(
                {
                    "code": item.get("code"),
                    "severity": item.get("severity"),
                    "slot": item.get("slot"),
                    "message": str(item.get("message") or "")[:240],
                }
            )
    fix = state.get("fix_plan") or {}
    return {
        "goal": "Produce final meditation MP3 from the compose brief, with QA gates.",
        "stage": state.get("stage"),
        "correlation_id": state.get("correlation_id"),
        "brief": {
            "generation_code": brief.get("generation_code"),
            "wound_id": brief.get("wound_id"),
            "stage_no": brief.get("stage_no"),
            "pillar_code": brief.get("pillar_code"),
            "title_hint": brief.get("title_hint"),
            "target_duration_minutes": brief.get("target_duration_minutes"),
            "has_repair_context": bool(brief.get("repair_context")),
        },
        "ids": {
            "transcript_id": state.get("transcript_id"),
            "audio_job_id": state.get("audio_job_id"),
            "local_mp3_path": state.get("local_mp3_path"),
        },
        "statuses": {
            "transcript": state.get("last_transcript_status"),
            "audio": state.get("last_audio_status"),
        },
        "budgets": {
            "compose_attempts": state.get("compose_attempts", 0),
            "repair_attempts": state.get("repair_attempts", 0),
            "enhance_attempts": state.get("enhance_attempts", 0),
            "tts_attempts": state.get("tts_attempts", 0),
            "brain_steps": state.get("brain_steps", 0),
        },
        "qa_report_present": bool(qa),
        "qa_issues": issues,
        "fix_plan_summary": fix.get("summary") if isinstance(fix, dict) else None,
        "last_error": (state.get("last_error") or "")[:500],
        "skip_tts": bool(state.get("skip_tts")),
        "recent_decisions": list(state.get("decision_log") or [])[-5:],
    }


def heuristic_decision(state: dict[str, Any], *, max_repairs: int) -> BrainDecision:
    """Safe fallback when OpenAI is unavailable or returns garbage."""
    if state.get("local_mp3_path") and state.get("stage") == "download":
        return BrainDecision(
            thought="MP3 path set; finish download stage if needed",
            action="download",
            reason="local path / download pending",
        )
    if state.get("stage") == "download" or (
        state.get("last_audio_status") == "COMPLETED" and not state.get("local_mp3_path")
    ):
        return BrainDecision(
            thought="Audio complete; download final file",
            action="download",
            reason="TTS completed",
        )
    if state.get("qa_report"):
        repairs = int(state.get("repair_attempts") or 0)
        if repairs >= max_repairs:
            return BrainDecision(
                thought="Repair budget exhausted",
                action="fail",
                reason="max compose repairs reached",
                fail_message="Compose QA failed; repair budget exhausted",
            )
        return BrainDecision(
            thought="QA report present; repair then recompose",
            action="repair_and_compose",
            reason="compose QA failure",
        )
    if not state.get("transcript_id"):
        return BrainDecision(
            thought="No transcript yet",
            action="compose",
            reason="start Agent 1",
        )
    status = state.get("last_transcript_status")
    if state.get("local_mp3_path") and state.get("last_audio_status") == "COMPLETED":
        return BrainDecision(
            thought="Final audio already on disk",
            action="complete",
            reason="pipeline finished",
        )
    if status in {"ENHANCED", "APPROVED"}:
        if state.get("skip_tts"):
            return BrainDecision(
                thought="Enhanced and skip_tts",
                action="complete",
                reason="skip_tts set",
            )
        if state.get("last_audio_status") == "COMPLETED" and not state.get("local_mp3_path"):
            return BrainDecision(
                thought="Need download",
                action="download",
                reason="audio completed",
            )
        return BrainDecision(
            thought="Transcript enhanced; run TTS",
            action="tts",
            reason=f"status={status}",
        )
    if status in {"FAILED_ENHANCEMENT", "REVIEW_REQUIRED", "PENDING_ENHANCEMENT", "ENHANCING", "CREATED", None}:
        return BrainDecision(
            thought="Need or continue enhancement",
            action="enhance",
            reason=f"status={status}",
        )
    return BrainDecision(
        thought="Unrecognized state",
        action="fail",
        reason="no heuristic path",
        fail_message=f"Cannot decide next step from stage={state.get('stage')} status={status}",
    )


class OrchestratorBrain:
    """OpenAI-backed next-action chooser for the agentic pipeline loop."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        client: Any | None = None,
        max_repairs: int = 3,
    ) -> None:
        from transcript_composer.llm_config import require_openai_api_key, resolve_openai_model

        self._model = model or resolve_openai_model()
        self._max_repairs = max_repairs
        self._client = client or self._build_client(api_key or require_openai_api_key())

    def decide(self, state: dict[str, Any]) -> BrainDecision:
        observation = build_observation(state)
        user_prompt = (
            "OBSERVATION (authoritative):\n"
            f"{json.dumps(observation, ensure_ascii=True, indent=2)}\n\n"
            "Choose the single next action."
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
                raise RuntimeError("empty brain response")
            decision = BrainDecision.model_validate(json.loads(content)).normalized()
            return self._rail(decision, state)
        except Exception as exc:  # noqa: BLE001
            logger.warning("orchestrator brain fallback to heuristic: %s", exc)
            return self._rail(heuristic_decision(state, max_repairs=self._max_repairs), state)

    def _rail(self, decision: BrainDecision, state: dict[str, Any]) -> BrainDecision:
        """Enforce hard sequencing rails the model might ignore."""
        action = decision.action
        qa = state.get("qa_report")
        tid = state.get("transcript_id")
        status = state.get("last_transcript_status")
        repairs = int(state.get("repair_attempts") or 0)

        if action == "tts" and status not in {"ENHANCED", "APPROVED"}:
            if qa:
                return decision.model_copy(
                    update={
                        "action": "repair_and_compose",
                        "reason": "rail: blocked TTS before enhance; QA pending",
                    }
                )
            if not tid:
                return decision.model_copy(
                    update={"action": "compose", "reason": "rail: no transcript for TTS"}
                )
            return decision.model_copy(
                update={"action": "enhance", "reason": "rail: must enhance before TTS"}
            )

        if action == "enhance" and not tid:
            return decision.model_copy(
                update={"action": "compose", "reason": "rail: no transcript to enhance"}
            )

        if action == "download" and not state.get("audio_job_id") and status not in {
            "ENHANCED",
            "APPROVED",
        }:
            if not tid:
                return decision.model_copy(update={"action": "compose", "reason": "rail: start compose"})
            return decision.model_copy(update={"action": "enhance", "reason": "rail: not ready to download"})

        if action == "compose" and qa and repairs < self._max_repairs:
            return decision.model_copy(
                update={
                    "action": "repair_and_compose",
                    "reason": "rail: QA report present — repair before blind compose",
                }
            )

        if action == "repair_and_compose" and repairs >= self._max_repairs:
            return BrainDecision(
                thought=decision.thought,
                action="fail",
                reason="rail: repair budget exhausted",
                fail_message=decision.fail_message
                or "Compose QA failed; repair budget exhausted",
            )

        return decision

    @staticmethod
    def _build_client(api_key: str) -> Any:
        from openai import OpenAI

        return OpenAI(api_key=api_key)
