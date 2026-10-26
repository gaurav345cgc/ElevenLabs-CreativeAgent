"""Tests for Agent 1 post-compose transcript validation."""

from __future__ import annotations

from uuid import uuid4

import pytest

from models.agents import Agent1Output
from models.metadata import (
    DurationEstimate,
    RawPatternMetadata,
    ScriptSection,
    SectionedScriptContent,
    TaxonomyContext,
)
from models.requests import CreateTranscriptRequest
from models.validation import build_example_pattern_plan
from transcript_composer.composition_service import CompositionService
from transcript_composer.script_generator import TemplateScriptGenerator
from transcript_composer.validation import TranscriptValidationError, TranscriptValidator


@pytest.fixture(autouse=True)
def _disable_live_pain_pillar_qa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATIVE_AGENT_PAIN_PILLAR_QA", "off")


def _sample_request(**overrides) -> CreateTranscriptRequest:
    payload = {
        "tenant_id": uuid4(),
        "content_type": "guided_meditation",
        "generation_code": "millennial",
        "wound_id": "ml_02",
        "stage_no": 2,
        "target_duration_minutes": 5,
        "pillar_code": "p04",
    }
    payload.update(overrides)
    return CreateTranscriptRequest(**payload)


def test_template_compose_passes_validation() -> None:
    output = CompositionService(
        generator=TemplateScriptGenerator(),
        validator=TranscriptValidator(validation_mode="rules"),
    ).compose(_sample_request())
    assert output.metadata.validation_report is not None
    assert output.metadata.validation_report["passed"] is True


def test_validator_rejects_missing_sections() -> None:
    request = _sample_request()
    plan = build_example_pattern_plan()
    output = Agent1Output(
        transcript_id=uuid4(),
        version_id=uuid4(),
        title="Test",
        transcript_text="too short",
        sectioned_script=SectionedScriptContent(
            sections=[
                ScriptSection(slot="opening", text=" ".join(["word"] * 30)),
            ]
        ),
        pattern_plan=plan,
        taxonomy=TaxonomyContext(
            generation_code=request.generation_code,
            wound_id=request.wound_id,
            stage_no=request.stage_no,
            pillar_code=request.pillar_code,
        ),
        duration_estimate=DurationEstimate(seconds=120),
        metadata=RawPatternMetadata(
            taxonomy=TaxonomyContext(
                generation_code=request.generation_code,
                wound_id=request.wound_id,
                stage_no=request.stage_no,
                pillar_code=request.pillar_code,
            ),
            pattern_plan=plan,
            duration_estimate=DurationEstimate(seconds=120),
            title="Test",
        ),
    )
    try:
        TranscriptValidator(validation_mode="rules").validate_or_raise(request, output)
    except TranscriptValidationError as exc:
        assert exc.report.error_count >= 1
        assert any(issue.code == "section_count" for issue in exc.report.issues)
    else:
        raise AssertionError("expected validation failure")


def test_validator_flags_composer_guidance_leakage() -> None:
    request = _sample_request()
    plan = build_example_pattern_plan()
    leaked = "Tell the listener what this session is for. Frame it around their specific wound."
    sections = [
        ScriptSection(slot=slot, text=leaked if slot == "opening" else " ".join(["notice"] * 30))
        for slot in ("opening", "settling", "body", "breath", "mind_heart", "closing")
    ]
    output = Agent1Output(
        transcript_id=uuid4(),
        version_id=uuid4(),
        title="Test",
        transcript_text="\n\n".join(section.text for section in sections),
        sectioned_script=SectionedScriptContent(sections=sections),
        pattern_plan=plan,
        taxonomy=TaxonomyContext(
            generation_code=request.generation_code,
            wound_id=request.wound_id,
            stage_no=request.stage_no,
            pillar_code=request.pillar_code,
        ),
        duration_estimate=DurationEstimate(seconds=300),
        metadata=RawPatternMetadata(
            taxonomy=TaxonomyContext(
                generation_code=request.generation_code,
                wound_id=request.wound_id,
                stage_no=request.stage_no,
                pillar_code=request.pillar_code,
            ),
            pattern_plan=plan,
            duration_estimate=DurationEstimate(seconds=300),
            title="Test",
        ),
    )
    with __import__("pytest").raises(TranscriptValidationError) as exc_info:
        TranscriptValidator(validation_mode="rules").validate_or_raise(request, output)
    assert any(
        issue.code == "composer_guidance_leaked" for issue in exc_info.value.report.issues
    )

    request = _sample_request()
    plan = build_example_pattern_plan()
    excerpt = (
        "i invite you to make yourself as comfortable as possible you can choose to be seated or lying down "
        "comfort and the feeling of safety are both very important for this practice choose a position "
        "that you don't have to use a lot of effort to stay in"
    )
    sections = [
        ScriptSection(slot=slot, text=excerpt if slot == "settling" else " ".join(["notice"] * 30))
        for slot in ("opening", "settling", "body", "breath", "mind_heart", "closing")
    ]
    output = Agent1Output(
        transcript_id=uuid4(),
        version_id=uuid4(),
        title="Test",
        transcript_text="\n\n".join(section.text for section in sections),
        sectioned_script=SectionedScriptContent(sections=sections),
        pattern_plan=plan,
        taxonomy=TaxonomyContext(
            generation_code=request.generation_code,
            wound_id=request.wound_id,
            stage_no=request.stage_no,
            pillar_code=request.pillar_code,
        ),
        duration_estimate=DurationEstimate(seconds=300),
        metadata=RawPatternMetadata(
            taxonomy=TaxonomyContext(
                generation_code=request.generation_code,
                wound_id=request.wound_id,
                stage_no=request.stage_no,
                pillar_code=request.pillar_code,
            ),
            pattern_plan=plan,
            duration_estimate=DurationEstimate(seconds=300),
            title="Test",
        ),
    )
    with __import__("pytest").raises(TranscriptValidationError) as exc_info:
        TranscriptValidator(validation_mode="rules").validate_or_raise(request, output)
    assert any(
        issue.code == "verbatim_example_copy" for issue in exc_info.value.report.issues
    )
