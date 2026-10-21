"""Unit tests for Agent 1 composition service."""

from __future__ import annotations

from uuid import uuid4

from models.enums import TranscriptStatus
from models.requests import CreateTranscriptRequest
from models.validation import COMPOSITION_SLOTS, validate_pattern_plan
from transcript_composer.composition_service import CompositionService
from transcript_composer.duration import estimate_duration_seconds
from transcript_composer.script_generator import TemplateScriptGenerator
from transcript_composer.title import build_title


def _sample_request(**overrides) -> CreateTranscriptRequest:
    payload = {
        "tenant_id": uuid4(),
        "content_type": "guided_meditation",
        "generation_code": "millennial",
        "wound_id": "ml_02",
        "stage_no": 2,
        "target_duration_minutes": 12,
        "pillar_code": "p04",
        "title_hint": "Evening unwind",
    }
    payload.update(overrides)
    return CreateTranscriptRequest(**payload)


def test_build_title_prefers_hint() -> None:
    request = _sample_request(title_hint="Custom title")
    assert build_title(request) == "Custom title"


def test_build_title_derives_from_taxonomy() -> None:
    request = _sample_request(title_hint=None)
    title = build_title(request)
    assert "chronic overextension" in title.lower()
    assert "stage 2" in title.lower()


def test_estimate_duration_from_text() -> None:
    estimate = estimate_duration_seconds("word " * 130)
    assert estimate.seconds == 60
    assert estimate.method == "word_count_heuristic"


def test_composition_service_produces_agent1_output() -> None:
    request = _sample_request()
    output = CompositionService(generator=TemplateScriptGenerator()).compose(request)

    assert output.status == TranscriptStatus.PENDING_ENHANCEMENT
    assert output.title == "Evening unwind"
    assert len(output.sectioned_script.sections) == len(COMPOSITION_SLOTS)
    assert output.transcript_text
    validate_pattern_plan(output.pattern_plan)
    assert output.metadata.pattern_plan == output.pattern_plan
    assert output.metadata.example_reference_ids
    assert output.duration_estimate.seconds >= 60
    assert output.created_by_agent == "pattern_transcript_composer"
    assert output.metadata.script_generator == "template"
    assert output.metadata.validation_report is not None
    assert output.metadata.validation_report["passed"] is True


def test_composition_preserves_six_stage_order() -> None:
    request = _sample_request()
    output = CompositionService(generator=TemplateScriptGenerator()).compose(request)
    slots = [section.slot for section in output.sectioned_script.sections]
    assert slots == list(COMPOSITION_SLOTS)
