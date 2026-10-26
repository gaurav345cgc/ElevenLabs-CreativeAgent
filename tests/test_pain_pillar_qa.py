"""Tests for relatability better-match floor + grounded pain/pillar QA."""

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
from transcript_composer.validation.models import ValidationIssue, ValidationSeverity
from transcript_composer.validation.pain_pillar_agent import (
    PainPillarAgent,
    _LlmIssue,
    _LlmPayload,
    _ground_issues,
    evidence_quote_in_script,
)
from transcript_composer.validation.rules import check_relatability_pack
from transcript_composer.validation.transcript_validator import TranscriptValidator


@pytest.fixture(autouse=True)
def _disable_live_pain_pillar_qa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATIVE_AGENT_PAIN_PILLAR_QA", "off")


def _wk06_request(**overrides) -> CreateTranscriptRequest:
    payload = {
        "tenant_id": uuid4(),
        "content_type": "guided_meditation",
        "generation_code": "gen_x",
        "wound_id": "wk_06",
        "stage_no": 2,
        "target_duration_minutes": 5,
        "pillar_code": "p05",
        "title_hint": "WK-06 Tech Obsolescence Anxiety",
    }
    payload.update(overrides)
    return CreateTranscriptRequest(**payload)


def _filler(words: int = 30) -> str:
    return " ".join(["notice"] * words)


def _sectioned(texts: dict[str, str]) -> SectionedScriptContent:
    return SectionedScriptContent(
        sections=[
            ScriptSection(slot=slot, text=texts.get(slot, _filler()))
            for slot in ("opening", "settling", "body", "breath", "mind_heart", "closing")
        ]
    )


def test_evidence_quote_in_script_requires_real_substring() -> None:
    script = "There's a moment in that meeting when the new screen opens."
    assert evidence_quote_in_script("moment in that meeting", script)
    assert not evidence_quote_in_script("they feel completely obsolete forever", script)
    assert not evidence_quote_in_script("short", script)


def test_ground_issues_drops_hallucinated_error_evidence() -> None:
    script = "## [opening]\nJust breathe and feel calm in your body."
    payload = _LlmPayload(
        passed=False,
        wound_score=0.2,
        pillar_score=0.2,
        issues=[
            _LlmIssue(
                code="pain_pillar_wound_weak",
                severity="error",
                message="not specific",
                slot="opening",
                evidence_quote="dashboard sync left them obsolete at work",
            ),
            _LlmIssue(
                code="pain_pillar_generic",
                severity="error",
                message="generic calm",
                slot="opening",
                evidence_quote="Just breathe and feel calm",
            ),
        ],
    )
    issues = _ground_issues(payload, script)
    assert len(issues) == 1
    assert issues[0].code == "pain_pillar_generic"
    assert issues[0].severity is ValidationSeverity.ERROR


def test_fail_if_better_matches_flags_rival_bleed() -> None:
    """WK-06 script that fully hits WK-05 groups more than its own should fail."""
    # Full WK-05 keyword coverage (purpose/hollow) with almost no WK-06 tech cues.
    wk05_heavy = (
        "Somewhere in the job the why returns — meaning and purpose feel hollow, "
        "technically fine on paper, successful but quiet: is this it? "
        "You keep searching, sitting with the open question of this work."
    )
    sectioned = _sectioned(
        {
            "opening": wk05_heavy + " " + _filler(20),
            "mind_heart": wk05_heavy + " " + _filler(20),
            "closing": wk05_heavy + " " + _filler(20),
        }
    )
    issues = check_relatability_pack(_wk06_request(), sectioned)
    codes = {issue.code for issue in issues}
    assert "relatability_better_match" in codes


def test_relatability_always_on_in_rules_mode() -> None:
    request = _wk06_request()
    plan = build_example_pattern_plan()
    # Generic calm — no work/tech/behind cues → relatability_keywords_missing
    sections = [
        ScriptSection(slot=slot, text=_filler(40))
        for slot in ("opening", "settling", "body", "breath", "mind_heart", "closing")
    ]
    output = Agent1Output(
        transcript_id=uuid4(),
        version_id=uuid4(),
        title="Test",
        transcript_text="\n\n".join(s.text for s in sections),
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
    report = TranscriptValidator(validation_mode="rules").validate(request, output)
    assert report.passed is False
    assert any(i.code == "relatability_keywords_missing" for i in report.issues)


def test_injected_pain_pillar_agent_errors_block() -> None:
    class _StubAgent:
        def judge(self, request, output):  # noqa: ANN001
            return [
                ValidationIssue(
                    code="pain_pillar_wound_weak",
                    severity=ValidationSeverity.ERROR,
                    message="wound not landed (evidence: feel calm in your body)",
                    slot="opening",
                    source="pain_pillar_qa",
                )
            ]

    request = _wk06_request()
    plan = build_example_pattern_plan()
    good = (
        "In that meeting the new tool on the screen leaves you a half-second behind at work. "
        "You want clarity — to untangle what years of judgment still mean. "
        "Keep up is not the only measure. Experience still lives in the body."
    )
    sections = [
        ScriptSection(slot=slot, text=good + " " + _filler(15))
        for slot in ("opening", "settling", "body", "breath", "mind_heart", "closing")
    ]
    output = Agent1Output(
        transcript_id=uuid4(),
        version_id=uuid4(),
        title="WK-06",
        transcript_text="\n\n".join(s.text for s in sections),
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
            title="WK-06",
        ),
    )
    report = TranscriptValidator(
        validation_mode="rules",
        pain_pillar_agent=_StubAgent(),  # type: ignore[arg-type]
    ).validate(request, output)
    assert any(i.code == "pain_pillar_wound_weak" for i in report.issues)
    assert report.passed is False


def test_pain_pillar_agent_type_export() -> None:
    assert PainPillarAgent is not None
