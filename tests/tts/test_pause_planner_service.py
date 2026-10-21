"""Phase 8: pause plan persistence / idempotency."""

from __future__ import annotations

from tts_pipeline.pause_planner.policy import (
    PAUSE_POLICY_VERSION,
    PROMPT_VERSION,
    clamp_hold_seconds,
)
from tts_pipeline.pause_planner.schema import (
    MappedPauseHold,
    MappedPausePlan,
    PauseHold,
    PauseHoldKind,
    PausePlan,
    PausePlannerProvider,
)
from tts_pipeline.pause_planner.service import (
    MAPPED_PAUSE_PLAN_KEY,
    PAUSE_PLAN_CLAMPED_EVENT,
    PAUSE_PLAN_CREATED_EVENT,
    PAUSE_PLAN_KEY,
    PAUSE_PLAN_MAPPED_EVENT,
    PAUSE_PLAN_REUSED_EVENT,
    PAUSE_PLAN_VERSIONS_KEY,
    InMemoryPausePlanStore,
    create_or_load_pause_plan,
    persist_mapped_pause_plan,
)


def _plan(*, seconds: int = 12, model: str = "gpt-4o-mini") -> PausePlan:
    # Speech nearly fills wall-clock so underfill expansion does not rewrite
    # the factory's hold lengths (tests assert exact seconds).
    return PausePlan(
        planner=PausePlannerProvider.OPENAI,
        model=model,
        prompt_version=PROMPT_VERSION,
        policy_version=PAUSE_POLICY_VERSION,
        target_duration_seconds=600,
        estimated_speech_seconds=590,
        total_hold_seconds=0,
        holds=[
            PauseHold(
                hold_id="h1",
                after_beat_index=0,
                hold_seconds=seconds,
                kind=PauseHoldKind.PRACTICE,
                reason="absorb cue",
            )
        ],
    )


def test_create_pause_plan_persists_metadata_and_events() -> None:
    store = InMemoryPausePlanStore()
    calls = {"n": 0}

    def factory() -> PausePlan:
        calls["n"] += 1
        return _plan(seconds=12)

    result = create_or_load_pause_plan(store, plan_factory=factory)
    assert result.created is True
    assert result.reused is False
    assert calls["n"] == 1
    assert PAUSE_PLAN_KEY in store.metadata
    assert PAUSE_PLAN_VERSIONS_KEY in store.metadata
    assert store.metadata[PAUSE_PLAN_VERSIONS_KEY]["policy_version"] == PAUSE_POLICY_VERSION
    assert store.events[0][0] == PAUSE_PLAN_CREATED_EVENT


def test_second_run_reuses_plan_without_factory_call() -> None:
    store = InMemoryPausePlanStore()
    calls = {"n": 0}

    def factory() -> PausePlan:
        calls["n"] += 1
        return _plan(seconds=12)

    first = create_or_load_pause_plan(store, plan_factory=factory)
    second = create_or_load_pause_plan(store, plan_factory=factory)
    assert first.created is True
    assert second.reused is True
    assert second.created is False
    assert calls["n"] == 1  # SQS duplicate safe
    assert second.plan == first.plan
    assert store.events[-1][0] == PAUSE_PLAN_REUSED_EVENT
    # Plan payload unchanged on reuse
    assert store.metadata[PAUSE_PLAN_KEY]["holds"][0]["hold_seconds"] == 12


def test_version_mismatch_replans() -> None:
    store = InMemoryPausePlanStore(
        {
            PAUSE_PLAN_KEY: _plan(seconds=10).model_dump(mode="json"),
            PAUSE_PLAN_VERSIONS_KEY: {
                "policy_version": "pause-old",
                "prompt_version": "pause-prompt-old",
                "model": "gpt-4o-mini",
            },
        }
    )

    result = create_or_load_pause_plan(
        store,
        plan_factory=lambda: _plan(seconds=14),
        force_replan=False,
    )
    assert result.created is True
    assert result.reused is False
    assert store.metadata[PAUSE_PLAN_KEY]["holds"][0]["hold_seconds"] == 14
    assert store.metadata[PAUSE_PLAN_VERSIONS_KEY]["prompt_version"] == PROMPT_VERSION


def test_force_replan_calls_factory_again() -> None:
    store = InMemoryPausePlanStore()
    create_or_load_pause_plan(store, plan_factory=lambda: _plan(seconds=12))
    result = create_or_load_pause_plan(
        store,
        plan_factory=lambda: _plan(seconds=8),
        force_replan=True,
    )
    assert result.created is True
    assert store.metadata[PAUSE_PLAN_KEY]["holds"][0]["hold_seconds"] == 8


def test_clamped_plan_emits_clamp_event() -> None:
    store = InMemoryPausePlanStore()
    # 200s practice clamps to practice max (15s)
    result = create_or_load_pause_plan(store, plan_factory=lambda: _plan(seconds=200))
    assert result.clamped is True
    assert result.after_total_hold_seconds == clamp_hold_seconds(200, PauseHoldKind.PRACTICE)
    event_types = [event_type for event_type, _ in store.events]
    assert PAUSE_PLAN_CREATED_EVENT in event_types
    assert PAUSE_PLAN_CLAMPED_EVENT in event_types
    clamp_payload = next(payload for event_type, payload in store.events if event_type == PAUSE_PLAN_CLAMPED_EVENT)
    assert clamp_payload is not None
    assert clamp_payload["before_total_hold_seconds"] == 200
    assert clamp_payload["after_total_hold_seconds"] == 15


def test_persist_mapped_pause_plan() -> None:
    store = InMemoryPausePlanStore()
    mapped = MappedPausePlan(
        total_hold_seconds=12,
        holds=[
            MappedPauseHold(
                hold_id="h1",
                after_beat_index=0,
                after_chunk_index=1,
                hold_seconds=12,
                kind=PauseHoldKind.PRACTICE,
                reason="absorb",
            )
        ],
    )
    persist_mapped_pause_plan(store, mapped)
    assert MAPPED_PAUSE_PLAN_KEY in store.metadata
    assert store.events[-1][0] == PAUSE_PLAN_MAPPED_EVENT
    assert store.events[-1][1]["after_chunk_indexes"] == [1]
