"""Tests for OpenAI-based transcript validation."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

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
from transcript_composer.validation.llm_validator import OpenAITranscriptValidator
from transcript_composer.validation.models import ValidationSeverity
from transcript_composer.validation.transcript_validator import TranscriptValidator


def _sample_request() -> CreateTranscriptRequest:
    return CreateTranscriptRequest(
        tenant_id=uuid4(),
        content_type="guided_meditation",
        generation_code="millennial",
        wound_id="ml_02",
        stage_no=2,
        target_duration_minutes=5,
        pillar_code="p04",
    )


def _sample_output() -> Agent1Output:
    request = _sample_request()
    plan = build_example_pattern_plan()
    sections = [
        ScriptSection(slot=slot, text=" ".join(["notice"] * 30))
        for slot in ("opening", "settling", "body", "breath", "mind_heart", "closing")
    ]
    return Agent1Output(
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


def _mock_openai_client(payload: dict) -> object:
    message = SimpleNamespace(content=json.dumps(payload))
    choice = SimpleNamespace(message=message)
    response = SimpleNamespace(choices=[choice])

    completions = SimpleNamespace(create=lambda **kwargs: response)
    chat = SimpleNamespace(completions=completions)
    return SimpleNamespace(chat=chat)


def test_openai_validator_parses_passing_response() -> None:
    client = _mock_openai_client({"passed": True, "issues": []})
    validator = OpenAITranscriptValidator(client=client, api_key="test-key")
    request = _sample_request()
    output = _sample_output()

    report = validator.validate(
        request,
        output,
        pattern_by_family={},
        examples=__import__(
            "transcript_composer.knowledge.loader", fromlist=["get_examples"]
        ).get_examples(),
    )

    assert report.passed is True
    assert report.error_count == 0


def test_openai_validator_parses_issues() -> None:
    client = _mock_openai_client(
        {
            "passed": False,
            "issues": [
                {
                    "code": "tone_mismatch",
                    "severity": "warn",
                    "message": "Settling section sounds too commanding.",
                    "slot": "settling",
                }
            ],
        }
    )
    validator = OpenAITranscriptValidator(client=client, api_key="test-key")
    report = validator.validate(
        _sample_request(),
        _sample_output(),
        pattern_by_family={},
        examples=__import__(
            "transcript_composer.knowledge.loader", fromlist=["get_examples"]
        ).get_examples(),
    )

    assert report.passed is True
    assert report.warning_count == 1
    assert report.issues[0].source == "llm"
    assert report.issues[0].severity == ValidationSeverity.WARN


def test_transcript_validator_openai_mode_merges_hard_checks() -> None:
    request = _sample_request()
    output = _sample_output()
    output.sectioned_script = SectionedScriptContent(
        sections=[ScriptSection(slot="opening", text="too short")]
    )

    client = _mock_openai_client({"passed": True, "issues": []})
    llm = OpenAITranscriptValidator(client=client, api_key="test-key")
    report = TranscriptValidator(
        validation_mode="openai",
        llm_validator=llm,
    ).validate(request, output)

    assert report.validator == "openai"
    assert report.passed is False
    assert any(issue.code == "section_count" for issue in report.issues)
