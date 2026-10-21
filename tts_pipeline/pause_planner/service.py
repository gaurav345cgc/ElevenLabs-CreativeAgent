"""Persist pause plans on audio-job metadata (idempotent, auditable)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from uuid import UUID

from tts_pipeline.pause_planner.errors import PausePlannerError, PausePlannerValidationError
from tts_pipeline.pause_planner.human_markers import HUMAN_PROMPT_VERSION
from tts_pipeline.pause_planner.policy import (
    PAUSE_POLICY_VERSION,
    PROMPT_VERSION,
    normalize_pause_plan,
)
from tts_pipeline.pause_planner.schema import MappedPausePlan, PausePlan, PausePlannerProvider

logger = logging.getLogger("creative_agent.tts.pause_planner")

PAUSE_PLAN_KEY = "pause_plan"
MAPPED_PAUSE_PLAN_KEY = "mapped_pause_plan"
PAUSE_PLAN_VERSIONS_KEY = "pause_plan_versions"

PAUSE_PLAN_CREATED_EVENT = "PAUSE_PLAN_CREATED"
PAUSE_PLAN_REUSED_EVENT = "PAUSE_PLAN_REUSED"
PAUSE_PLAN_MAPPED_EVENT = "PAUSE_PLAN_MAPPED"
PAUSE_PLAN_CLAMPED_EVENT = "PAUSE_PLAN_CLAMPED"

PlanFactory = Callable[[], PausePlan]


class PausePlanStore(Protocol):
    """Minimal persistence surface for pause-plan service tests and adapters."""

    def get_metadata(self) -> dict[str, Any]: ...

    def merge_metadata(self, patch: dict[str, Any]) -> dict[str, Any]: ...

    def record_event(self, event_type: str, payload: dict[str, Any] | None = None) -> None: ...


@dataclass(frozen=True, slots=True)
class CreateOrLoadPausePlanResult:
    plan: PausePlan
    created: bool
    reused: bool
    clamped: bool
    before_total_hold_seconds: int | None = None
    after_total_hold_seconds: int | None = None


@dataclass
class InMemoryPausePlanStore:
    """Fake store for unit tests — SQS-duplicate safe via metadata reuse."""

    metadata: dict[str, Any]
    events: list[tuple[str, dict[str, Any] | None]]

    def __init__(self, metadata: dict[str, Any] | None = None) -> None:
        self.metadata = dict(metadata or {})
        self.events = []

    def get_metadata(self) -> dict[str, Any]:
        return dict(self.metadata)

    def merge_metadata(self, patch: dict[str, Any]) -> dict[str, Any]:
        self.metadata = {**self.metadata, **patch}
        return dict(self.metadata)

    def record_event(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.events.append((event_type, payload))


class SessionPausePlanStore:
    """Adapter over ``AudioJobRepository`` + SQLAlchemy session."""

    def __init__(
        self,
        *,
        session: Any,
        repository: Any,
        audio_job_id: UUID,
        correlation_id: str | None = None,
    ) -> None:
        self._session = session
        self._repository = repository
        self._audio_job_id = audio_job_id
        self._correlation_id = correlation_id

    def get_metadata(self) -> dict[str, Any]:
        job = self._repository.get_audio_job(self._session, self._audio_job_id)
        if job is None:
            raise PausePlannerError(f"audio job {self._audio_job_id} not found")
        return dict(job.metadata_json or {})

    def merge_metadata(self, patch: dict[str, Any]) -> dict[str, Any]:
        job = self._repository.merge_audio_job_metadata(
            self._session,
            self._audio_job_id,
            patch,
            correlation_id=self._correlation_id,
        )
        return dict(job.metadata_json or {})

    def record_event(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self._repository.record_audio_event(
            self._session,
            self._audio_job_id,
            event_type,
            payload,
            correlation_id=self._correlation_id,
        )


def create_or_load_pause_plan(
    store: PausePlanStore,
    *,
    plan_factory: PlanFactory,
    force_replan: bool = False,
    target_duration_seconds: int | None = None,
    estimated_speech_seconds: int | None = None,
) -> CreateOrLoadPausePlanResult:
    """Load existing pause plan or create/normalize a new one.

    Idempotency:
    - Existing plan + matching versions → reuse (no ``plan_factory`` call).
    - Missing plan, mismatched versions, or ``force_replan=True`` → call
      ``plan_factory``, normalize, persist (so prompt/policy bumps take effect).
    """
    metadata = store.get_metadata()
    existing = _load_pause_plan(metadata.get(PAUSE_PLAN_KEY))
    versions = metadata.get(PAUSE_PLAN_VERSIONS_KEY) or {}

    if existing is not None and not force_replan and _versions_match(existing, versions):
        store.record_event(
            PAUSE_PLAN_REUSED_EVENT,
            {
                "reason": "versions_match",
                "hold_count": len(existing.holds),
                "total_hold_seconds": existing.total_hold_seconds,
                "pause_plan_versions": _version_payload(existing),
            },
        )
        return CreateOrLoadPausePlanResult(plan=existing, created=False, reused=True, clamped=False)

    if existing is not None and not force_replan:
        logger.info(
            "pause plan versions mismatch; replanning "
            "stored=%s current_policy=%s current_prompt=%s",
            versions,
            PAUSE_POLICY_VERSION,
            PROMPT_VERSION,
        )

    raw_plan = plan_factory()
    if not isinstance(raw_plan, PausePlan):
        raise PausePlannerValidationError("plan_factory must return a PausePlan")

    before_total = sum(hold.hold_seconds for hold in raw_plan.holds)
    normalized = normalize_pause_plan(
        raw_plan,
        target_duration_seconds=target_duration_seconds,
        estimated_speech_seconds=estimated_speech_seconds,
    )
    after_total = normalized.total_hold_seconds
    clamped = before_total != after_total or any(
        raw.hold_seconds != norm.hold_seconds
        for raw, norm in zip(raw_plan.holds, normalized.holds, strict=False)
    ) or len(raw_plan.holds) != len(normalized.holds)

    store.merge_metadata(
        {
            PAUSE_PLAN_KEY: normalized.model_dump(mode="json"),
            PAUSE_PLAN_VERSIONS_KEY: _version_payload(normalized),
        }
    )
    store.record_event(
        PAUSE_PLAN_CREATED_EVENT,
        {
            "hold_count": len(normalized.holds),
            "total_hold_seconds": normalized.total_hold_seconds,
            "force_replan": force_replan,
            "pause_plan_versions": _version_payload(normalized),
        },
    )
    if clamped:
        store.record_event(
            PAUSE_PLAN_CLAMPED_EVENT,
            {
                "before_total_hold_seconds": before_total,
                "after_total_hold_seconds": after_total,
                "before_hold_count": len(raw_plan.holds),
                "after_hold_count": len(normalized.holds),
            },
        )

    return CreateOrLoadPausePlanResult(
        plan=normalized,
        created=True,
        reused=False,
        clamped=clamped,
        before_total_hold_seconds=before_total,
        after_total_hold_seconds=after_total,
    )


def persist_mapped_pause_plan(
    store: PausePlanStore,
    mapped: MappedPausePlan,
) -> MappedPausePlan:
    """Persist mapped plan and emit ``PAUSE_PLAN_MAPPED``."""
    store.merge_metadata({MAPPED_PAUSE_PLAN_KEY: mapped.model_dump(mode="json")})
    store.record_event(
        PAUSE_PLAN_MAPPED_EVENT,
        {
            "hold_count": len(mapped.holds),
            "total_hold_seconds": mapped.total_hold_seconds,
            "after_chunk_indexes": [hold.after_chunk_index for hold in mapped.holds],
        },
    )
    return mapped


def _version_payload(plan: PausePlan) -> dict[str, str]:
    return {
        "policy_version": plan.policy_version,
        "prompt_version": plan.prompt_version,
        "model": plan.model,
    }


def _versions_match(plan: PausePlan, stored_versions: object) -> bool:
    """Reuse stored plan when policy still current and stored version stamp matches.

    Human Script Hub plans use ``human-markers-v1`` (not the OpenAI prompt version);
    they still replan when ``PAUSE_POLICY_VERSION`` bumps.
    """
    if plan.policy_version != PAUSE_POLICY_VERSION:
        return False

    if plan.planner is PausePlannerProvider.HUMAN:
        if not isinstance(stored_versions, dict):
            return plan.prompt_version == HUMAN_PROMPT_VERSION
        return (
            stored_versions.get("policy_version") == plan.policy_version
            and stored_versions.get("prompt_version") == plan.prompt_version
            and stored_versions.get("model") == plan.model
        )

    if not isinstance(stored_versions, dict):
        return plan.prompt_version == PROMPT_VERSION
    return (
        stored_versions.get("policy_version") == plan.policy_version
        and stored_versions.get("prompt_version") == plan.prompt_version == PROMPT_VERSION
        and stored_versions.get("model") == plan.model
    )


def _load_pause_plan(raw: object) -> PausePlan | None:
    if raw is None:
        return None
    if isinstance(raw, PausePlan):
        return raw
    if not isinstance(raw, dict):
        raise PausePlannerValidationError("stored pause_plan must be an object")
    try:
        return PausePlan.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        raise PausePlannerValidationError(f"stored pause_plan is invalid: {exc}") from exc
