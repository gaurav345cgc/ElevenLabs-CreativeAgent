"""Phase 3: OpenAI pause planner client with injectable transport."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tts_pipeline.pause_planner.errors import (
    PausePlannerError,
    PausePlannerTransientError,
    PausePlannerValidationError,
)
from tts_pipeline.pause_planner.openai_client import (
    DEFAULT_TEMPERATURE,
    OpenAIPausePlannerClient,
    resolve_pause_planner_model,
)


def _response(content: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def test_plan_pauses_returns_raw_dict_with_fake_transport() -> None:
    payload = {
        "holds": [
            {
                "hold_id": "h1",
                "after_beat_index": 0,
                "hold_seconds": 12,
                "kind": "practice",
                "reason": "absorb cue",
            }
        ]
    }
    calls: list[dict] = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return _response(json.dumps(payload))

    client = OpenAIPausePlannerClient(create_completion=fake_create, model="gpt-4o-mini")
    result = client.plan_pauses(
        beats=["Let your shoulders soften."],
        paragraphs=[],
        target_duration_seconds=600,
        estimated_speech_seconds=420,
    )
    assert result == payload
    assert client.last_latency_ms is not None
    assert client.last_latency_ms >= 0
    assert calls[0]["temperature"] == DEFAULT_TEMPERATURE
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[0]["model"] == "gpt-4o-mini"
    assert calls[0]["temperature"] <= 0.3


def test_plan_pauses_rejects_empty_anchors() -> None:
    client = OpenAIPausePlannerClient(create_completion=lambda **_: _response("{}"))
    with pytest.raises(PausePlannerValidationError, match="beats or paragraphs"):
        client.plan_pauses(
            beats=[],
            paragraphs=[],
            target_duration_seconds=600,
            estimated_speech_seconds=100,
        )


def test_plan_pauses_retries_transient_then_succeeds() -> None:
    attempts = {"n": 0}

    def flaky(**kwargs):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TimeoutError("timeout talking to openai")
        return _response('{"holds":[]}')

    client = OpenAIPausePlannerClient(
        create_completion=flaky,
        model="gpt-4o-mini",
        max_attempts=3,
    )
    assert client.plan_pauses(
        beats=["Breathe."],
        paragraphs=[],
        target_duration_seconds=300,
        estimated_speech_seconds=200,
    ) == {"holds": []}
    assert attempts["n"] == 3


def test_plan_pauses_raises_transient_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "tts_pipeline.pause_planner.openai_client.time.sleep",
        lambda *_args, **_kwargs: None,
    )

    def always_timeout(**kwargs):
        raise ConnectionError("connection reset")

    client = OpenAIPausePlannerClient(
        create_completion=always_timeout,
        model="gpt-4o-mini",
        max_attempts=2,
    )
    with pytest.raises(PausePlannerTransientError, match="after 2 attempts"):
        client.plan_pauses(
            beats=["Breathe."],
            paragraphs=[],
            target_duration_seconds=300,
            estimated_speech_seconds=200,
        )


def test_plan_pauses_rejects_non_json() -> None:
    client = OpenAIPausePlannerClient(
        create_completion=lambda **_: _response("not-json"),
        model="gpt-4o-mini",
    )
    with pytest.raises(PausePlannerValidationError, match="non-JSON"):
        client.plan_pauses(
            beats=["Breathe."],
            paragraphs=[],
            target_duration_seconds=300,
            estimated_speech_seconds=200,
        )


def test_temperature_guard() -> None:
    with pytest.raises(PausePlannerError, match="temperature"):
        OpenAIPausePlannerClient(
            create_completion=lambda **_: _response("{}"),
            temperature=0.9,
        )


def test_resolve_pause_planner_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATIVE_AGENT_PAUSE_PLANNER_MODEL", "gpt-4o")
    assert resolve_pause_planner_model() == "gpt-4o"
    monkeypatch.delenv("CREATIVE_AGENT_PAUSE_PLANNER_MODEL", raising=False)
    monkeypatch.setenv("CREATIVE_AGENT_OPENAI_MODEL", "gpt-4o-mini")
    assert resolve_pause_planner_model() == "gpt-4o-mini"
