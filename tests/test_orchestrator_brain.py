"""Tests for OpenAI Orchestrator Brain + agentic loop (mocked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from pipeline_orchestrator.agentic import execute_decision, run_agentic_pipeline
from pipeline_orchestrator.brain import (
    BrainDecision,
    OrchestratorBrain,
    build_observation,
    heuristic_decision,
)
from pipeline_orchestrator.client import CreativeAgentApiError
from pipeline_orchestrator.config import OrchestratorSettings
from pipeline_orchestrator.state import initial_state


@pytest.fixture
def settings(tmp_path: Path) -> OrchestratorSettings:
    return OrchestratorSettings(
        api_base_url="https://example.test",
        api_key="test-key",
        tenant_id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        poll_seconds=0.01,
        enhancement_timeout_seconds=1,
        tts_timeout_seconds=1,
        max_compose_repair_attempts=3,
        max_brain_steps=10,
        output_dir=tmp_path,
    )


def test_heuristic_compose_when_empty() -> None:
    d = heuristic_decision(initial_state(), max_repairs=3)
    assert d.action == "compose"


def test_heuristic_repair_when_qa_present() -> None:
    state = {
        **initial_state(),
        "qa_report": {"passed": False, "error_count": 1, "issues": []},
        "repair_attempts": 0,
    }
    d = heuristic_decision(state, max_repairs=3)
    assert d.action == "repair_and_compose"


def test_rail_blocks_tts_before_enhance() -> None:
    brain = OrchestratorBrain.__new__(OrchestratorBrain)
    brain._max_repairs = 3
    decision = BrainDecision(
        thought="rush",
        action="tts",
        reason="want audio",
    )
    railed = OrchestratorBrain._rail(
        brain,
        decision,
        {"transcript_id": "t1", "last_transcript_status": "PENDING_ENHANCEMENT"},
    )
    assert railed.action == "enhance"


def test_rail_forces_repair_over_blind_compose() -> None:
    brain = OrchestratorBrain.__new__(OrchestratorBrain)
    brain._max_repairs = 3
    decision = BrainDecision(thought="x", action="compose", reason="again")
    railed = OrchestratorBrain._rail(
        brain,
        decision,
        {
            "qa_report": {"passed": False, "issues": [{"code": "relatability_opening_weak"}]},
            "repair_attempts": 0,
        },
    )
    assert railed.action == "repair_and_compose"


def test_observation_is_compact() -> None:
    obs = build_observation(
        {
            **initial_state(),
            "compose_brief": {"wound_id": "wk_06", "pillar_code": "p05"},
            "qa_report": {
                "issues": [
                    {
                        "code": "pain_pillar_generic",
                        "severity": "error",
                        "message": "x" * 500,
                    }
                ]
            },
        }
    )
    assert obs["brief"]["wound_id"] == "wk_06"
    assert len(obs["qa_issues"][0]["message"]) <= 240


def test_agentic_loop_compose_enhance_with_stub_brain(settings: OrchestratorSettings) -> None:
    class _ScriptedBrain:
        def __init__(self) -> None:
            self.n = 0

        def decide(self, state: dict) -> BrainDecision:
            self.n += 1
            if not state.get("transcript_id"):
                return BrainDecision(thought="start", action="compose", reason="no tx")
            if state.get("last_transcript_status") != "ENHANCED":
                return BrainDecision(thought="enh", action="enhance", reason="need enhance")
            return BrainDecision(thought="done", action="complete", reason="skip audio")

    client = MagicMock()
    client.compose_transcript.return_value = {
        "transcript_id": "11111111-1111-1111-1111-111111111111",
        "status": "PENDING_ENHANCEMENT",
    }
    client.get_transcript.return_value = {"status": "ENHANCED"}
    client.wait_for_transcript_status.return_value = {"status": "ENHANCED"}

    brief = {
        "content_type": "guided_meditation",
        "generation_code": "millennial",
        "wound_id": "ml_02",
        "stage_no": 2,
        "target_duration_minutes": 5,
        "pillar_code": "p04",
    }
    final = run_agentic_pipeline(
        initial_state(skip_tts=True, compose_brief=brief),
        client=client,
        settings=settings,
        compose_brief=brief,
        brain=_ScriptedBrain(),  # type: ignore[arg-type]
        max_steps=8,
    )
    assert final["stage"] == "done"
    assert final["transcript_id"]
    assert any(d["action"] == "compose" for d in final["decision_log"])
    client.compose_transcript.assert_called()


def test_execute_repair_and_compose_passes_brain_instructions(
    settings: OrchestratorSettings,
) -> None:
    client = MagicMock()
    client.compose_transcript.side_effect = CreativeAgentApiError(
        "still bad",
        status_code=422,
        body={
            "details": {
                "validation_report": {
                    "passed": False,
                    "error_count": 1,
                    "issues": [
                        {
                            "code": "relatability_opening_weak",
                            "severity": "error",
                            "message": "weak",
                        }
                    ],
                }
            }
        },
    )
    state = {
        **initial_state(),
        "compose_brief": {"wound_id": "wk_06"},
        "qa_report": {
            "passed": False,
            "error_count": 1,
            "issues": [
                {
                    "code": "relatability_opening_weak",
                    "severity": "error",
                    "message": "weak",
                    "slot": "opening",
                }
            ],
        },
        "repair_attempts": 0,
    }
    decision = BrainDecision(
        thought="fix opening",
        action="repair_and_compose",
        reason="qa",
        composer_instructions="Name the meeting + screen in the first two lines.",
    )
    result = execute_decision(
        state,
        decision,
        client=client,
        settings=settings,
        compose_brief=state["compose_brief"],
    )
    # After repair, compose was called; QA failed again → qa_repair stage
    assert result["stage"] == "qa_repair"
    ctx = result["compose_brief"].get("repair_context") or {}
    # First repair set instructions; compose failed so brief may still hold repair_context
    # from the repair step before compose overwrote path — check decision log
    assert result["decision_log"][-1]["action"] == "repair_and_compose"
    # The compose call should have included repair_context with brain text
    call_brief = client.compose_transcript.call_args[0][0]
    assert "Orchestrator brain additions" in call_brief["repair_context"]["composer_instructions"]
    assert "meeting + screen" in call_brief["repair_context"]["composer_instructions"]
