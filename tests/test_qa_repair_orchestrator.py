"""Phase A: templated QA repair loop in the pipeline orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from models.requests import ComposeRepairContext, ComposeRepairIssue, CreateTranscriptRequest
from pipeline_orchestrator.client import CreativeAgentApiError
from pipeline_orchestrator.config import OrchestratorSettings
from pipeline_orchestrator.nodes import run_compose, run_qa_repair
from pipeline_orchestrator.qa_repair import build_fix_plan
from pipeline_orchestrator.state import initial_state
from transcript_composer.repair import format_repair_block


@pytest.fixture
def settings(tmp_path: Path) -> OrchestratorSettings:
    return OrchestratorSettings(
        api_base_url="https://example.test",
        api_key="test-key",
        tenant_id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        poll_seconds=0.01,
        max_compose_retries=2,
        max_compose_repair_attempts=3,
        output_dir=tmp_path,
    )


def test_build_fix_plan_maps_codes_to_instructions() -> None:
    plan = build_fix_plan(
        {
            "passed": False,
            "error_count": 2,
            "issues": [
                {
                    "code": "relatability_opening_weak",
                    "severity": "error",
                    "message": "opening needs theme hits",
                    "slot": "opening",
                },
                {
                    "code": "pain_pillar_wound_weak",
                    "severity": "error",
                    "message": "wound not landed",
                    "slot": "opening",
                },
            ],
        }
    )
    assert "relatability_opening_weak" in plan.root_causes
    assert "pain_pillar_wound_weak" in plan.root_causes
    assert "OPENING" in plan.composer_instructions or "opening" in plan.composer_instructions.lower()
    assert plan.should_retry is True


def test_format_repair_block_includes_instructions() -> None:
    request = CreateTranscriptRequest(
        tenant_id=uuid4(),
        content_type="guided_meditation",
        generation_code="millennial",
        wound_id="ml_02",
        stage_no=2,
        target_duration_minutes=5,
        pillar_code="p04",
        repair_context=ComposeRepairContext(
            previous_issues=[
                ComposeRepairIssue(
                    code="relatability_opening_weak",
                    message="opening weak",
                    slot="opening",
                )
            ],
            composer_instructions="1. Strengthen opening scene.",
            repair_attempt=2,
        ),
    )
    block = format_repair_block(request)
    assert "QA repair brief" in block
    assert "relatability_opening_weak" in block
    assert "Strengthen opening scene" in block


def test_compose_routes_422_qa_to_qa_repair(settings: OrchestratorSettings) -> None:
    client = MagicMock()
    report = {
        "passed": False,
        "error_count": 1,
        "issues": [
            {
                "code": "relatability_keywords_missing",
                "severity": "error",
                "message": "missing groups",
            }
        ],
    }
    client.compose_transcript.side_effect = CreativeAgentApiError(
        "compose failed (422)",
        status_code=422,
        body={
            "error_code": "VALIDATION_ERROR",
            "message": "Generated transcript failed pattern validation",
            "details": {"validation_report": report},
        },
    )
    brief = {
        "content_type": "guided_meditation",
        "generation_code": "millennial",
        "wound_id": "ml_02",
        "stage_no": 2,
        "target_duration_minutes": 5,
        "pillar_code": "p04",
    }
    state = {**initial_state(compose_brief=brief), "compose_brief": brief}
    result = run_compose(state, client=client, settings=settings, compose_brief=brief)
    assert result["stage"] == "qa_repair"
    assert result["qa_report"]["error_count"] == 1


def test_qa_repair_updates_brief_and_recomposes(settings: OrchestratorSettings) -> None:
    brief = {
        "content_type": "guided_meditation",
        "generation_code": "gen_x",
        "wound_id": "wk_06",
        "stage_no": 3,
        "target_duration_minutes": 10,
        "pillar_code": "p05",
        "title_hint": "WK-06",
    }
    state = {
        **initial_state(compose_brief=brief),
        "compose_brief": brief,
        "qa_report": {
            "passed": False,
            "error_count": 1,
            "issues": [
                {
                    "code": "relatability_opening_weak",
                    "severity": "error",
                    "message": "opening needs hits",
                    "slot": "opening",
                }
            ],
        },
        "repair_attempts": 0,
    }
    result = run_qa_repair(state, settings=settings)
    assert result["stage"] == "compose"
    assert result["repair_attempts"] == 1
    ctx = result["compose_brief"]["repair_context"]
    assert ctx["repair_attempt"] == 1
    assert "relatability_opening_weak" in ctx["composer_instructions"] or any(
        i["code"] == "relatability_opening_weak" for i in ctx["previous_issues"]
    )
    assert result["fix_plan"]["summary"]


def test_qa_repair_exhausted_writes_artifact(settings: OrchestratorSettings) -> None:
    state = {
        **initial_state(correlation_id="corr-qa-test"),
        "compose_brief": {"wound_id": "wk_06"},
        "qa_report": {
            "passed": False,
            "error_count": 1,
            "issues": [
                {
                    "code": "pain_pillar_generic",
                    "severity": "error",
                    "message": "too generic",
                }
            ],
        },
        "repair_attempts": 3,
    }
    result = run_qa_repair(state, settings=settings)
    assert result["stage"] == "failed"
    assert result["failed_agent"] == "compose"
    artifact = settings.output_dir / "qa-failure-corr-qa-test.json"
    assert artifact.is_file()
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["fix_plan"]["root_causes"] == ["pain_pillar_generic"]
