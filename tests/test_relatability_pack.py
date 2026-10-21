"""Relatability pack resolution and validator seeds."""

from __future__ import annotations

from models.metadata import ScriptSection, SectionedScriptContent
from models.requests import CreateTranscriptRequest
from transcript_composer.relatability import (
    extract_product_code_from_title,
    format_relatability_block,
    resolve_relatability_entry,
)
from transcript_composer.validation.rules import check_relatability_pack


def _req(**kwargs) -> CreateTranscriptRequest:
    base = dict(
        tenant_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        content_type="guided_meditation",
        generation_code="gen_x",
        wound_id="gx_02",
        stage_no=2,
        target_duration_minutes=10,
        pillar_code="p05",
    )
    base.update(kwargs)
    return CreateTranscriptRequest(**base)


def test_extract_product_code_from_title() -> None:
    assert extract_product_code_from_title("WK-06 Age / Tech — sample A") == "WK-06"
    assert extract_product_code_from_title("FR Friendship overlays — sample B") == "FR"
    assert extract_product_code_from_title("generic calm") is None


def test_resolve_wk06_from_title() -> None:
    entry = resolve_relatability_entry(
        _req(title_hint="WK-06 Age / Tech Obsolescence — sample A", wound_id="gx_02")
    )
    assert entry is not None
    assert entry["product_code"] == "WK-06"
    assert entry["pillar_code"] == "p05"
    block = format_relatability_block(
        _req(title_hint="WK-06 Age / Tech Obsolescence — sample A", wound_id="gx_02")
    )
    assert "Relatability brief" in block
    assert "must-use" in block.lower() or "Must-use" in block
    assert "mind_heart" in block.lower() or "Mind/heart" in block


def test_relatability_validator_flags_missing_keywords() -> None:
    req = _req(
        title_hint="PH-01 Chronic Pain — sample A",
        wound_id="bo_04",
        generation_code="boomer",
        pillar_code="p03",
        target_duration_minutes=15,
    )
    sectioned = SectionedScriptContent(
        sections=[
            ScriptSection(slot="opening", text="Welcome. Take a soft breath."),
            ScriptSection(slot="settling", text="Feel the chair and the floor."),
            ScriptSection(slot="body", text="Notice your shoulders."),
            ScriptSection(slot="breath", text="Breath arrives and leaves."),
            ScriptSection(slot="mind_heart", text="You are enough in this quiet."),
            ScriptSection(slot="closing", text="Carry this calm with you."),
        ]
    )
    issues = check_relatability_pack(req, sectioned)
    codes = {i.code for i in issues}
    assert "relatability_keywords_missing" in codes or "relatability_opening_weak" in codes


def test_relatability_validator_passes_anchored_script() -> None:
    req = _req(
        title_hint="WK-06 Age / Tech Obsolescence — sample A",
        wound_id="gx_02",
        generation_code="gen_x",
        pillar_code="p05",
    )
    sectioned = SectionedScriptContent(
        sections=[
            ScriptSection(
                slot="opening",
                text=(
                    "There's a meeting on the screen again, a new system moving fast, "
                    "and you feel a half-second behind at work."
                ),
            ),
            ScriptSection(
                slot="settling",
                text="Let the desk and the years of judgment rest for a moment.",
            ),
            ScriptSection(
                slot="body",
                text="Notice the jaw that tightens when the tools keep changing.",
            ),
            ScriptSection(
                slot="breath",
                text="A slower breath — room to untangle what is still true.",
            ),
            ScriptSection(
                slot="mind_heart",
                text=(
                    "See it more clearly: a dashboard updating overnight is not the same "
                    "as you becoming outdated. Your judgment from tenure still counts."
                ),
            ),
            ScriptSection(
                slot="closing",
                text="What you know in your hands is still yours, whatever screen opens next.",
            ),
        ]
    )
    issues = [i for i in check_relatability_pack(req, sectioned) if i.severity.value == "error"]
    assert issues == [], [i.message for i in issues]
