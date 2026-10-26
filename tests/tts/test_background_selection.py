"""Catalog bed selection (OpenAI + reviewer) tests."""

from __future__ import annotations

import json

import pytest

from tts_pipeline.background_policy import (
    DEFAULT_BACKGROUND_PROFILE_CODE,
    apply_reviewer_background_choice,
    resolve_background_profile,
)
from tts_pipeline.background_policy.resolver import BackgroundPolicyError
from tts_pipeline.background_policy.selection import (
    parse_background_selection_response,
    copy_background_metadata,
)


def test_parse_openai_selection_filters_unknown_codes() -> None:
    parsed = parse_background_selection_response(
        {
            "selected_code": "sanctuary",
            "reason": "Safety and rest for this wound.",
            "alternatives": [
                {"code": "the_deep", "reason": "If the script is heavier."},
                {"code": "not_real", "reason": "drop me"},
                {"code": "sanctuary", "reason": "duplicate"},
                {"code": "floating", "reason": "lighter neighbour"},
            ],
        },
        model="gpt-4o-mini",
    )
    assert parsed["selected_code"] == "sanctuary"
    assert parsed["selected_by"] == "openai"
    codes = [item["code"] for item in parsed["alternatives"]]
    assert "not_real" not in codes
    assert "sanctuary" not in codes
    assert codes[:2] == ["the_deep", "floating"]
    assert len(parsed["alternatives"]) == 3


def test_parse_rejects_unknown_selected_code() -> None:
    with pytest.raises(BackgroundPolicyError, match="unknown profile"):
        parse_background_selection_response(
            {"selected_code": "beach_waves", "reason": "nope", "alternatives": []},
            model="gpt-4o-mini",
        )


def test_reviewer_choice_promotes_previous_selected_to_alternatives() -> None:
    current = parse_background_selection_response(
        {
            "selected_code": "earth",
            "reason": "Grounded body practice.",
            "alternatives": [
                {"code": "replenish", "reason": "fatigue neighbour"},
                {"code": "sanctuary", "reason": "safer option"},
            ],
        },
        model="gpt-4o-mini",
    )
    updated = apply_reviewer_background_choice(current, "sanctuary")
    assert updated["selected_code"] == "sanctuary"
    assert updated["selected_by"] == "reviewer"
    alt_codes = [item["code"] for item in updated["alternatives"]]
    assert alt_codes[0] == "earth"
    assert "sanctuary" not in alt_codes


def test_resolve_uses_metadata_selected_code() -> None:
    profile = resolve_background_profile(
        metadata_json={
            "background_selection": {"selected_code": "floating"},
        }
    )
    assert profile.code == "floating"


def test_resolve_falls_back_when_code_unknown() -> None:
    profile = resolve_background_profile(requested_code="not_in_catalog")
    assert profile.code == DEFAULT_BACKGROUND_PROFILE_CODE


def test_copy_background_metadata() -> None:
    copied = copy_background_metadata(
        {
            "background_profile_code": "winter",
            "background_selection": {"selected_code": "winter"},
            "other": 1,
        }
    )
    assert copied == {
        "background_profile_code": "winter",
        "background_selection": {"selected_code": "winter"},
    }


def test_select_background_for_script_uses_openai_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tts_pipeline.background_policy import selection as selection_mod

    monkeypatch.setenv("CREATIVE_AGENT_BG_SELECTOR", "openai")

    class _FakeClient:
        model = "gpt-4o-mini"

        def select_background(self, **kwargs):
            assert kwargs["wound_id"] == "wk_06"
            assert kwargs["pillar_code"] == "p05"
            return {
                "selected_code": "timing",
                "reason": "Age/tech obsolescence at work needs measured pacing.",
                "alternatives": [
                    {"code": "earth", "reason": "grounded"},
                    {"code": "frozen_in_time", "reason": "suspended"},
                    {"code": "replenish", "reason": "fatigue"},
                ],
            }

    picked = selection_mod.select_background_for_script(
        content_text="You notice the tools moving faster than you can learn.",
        title="WK-06 Age / Tech Obsolescence",
        generation_code="gen_x",
        wound_id="wk_06",
        stage_no=3,
        pillar_code="p05",
        client=_FakeClient(),
    )
    assert picked["selected_code"] == "timing"
    assert picked["selected_by"] == "openai"


def test_select_background_for_script_off_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tts_pipeline.background_policy import selection as selection_mod

    monkeypatch.setenv("CREATIVE_AGENT_BG_SELECTOR", "off")
    picked = selection_mod.select_background_for_script(
        content_text="anything",
        wound_id="wk_06",
        pillar_code="p05",
    )
    assert picked["selected_code"] == DEFAULT_BACKGROUND_PROFILE_CODE
    assert picked["selected_by"] == "default"


def test_catalog_entries_include_listen_summaries() -> None:
    from tts_pipeline.background_policy.profiles import catalog_entries, listen_notes_for_code

    entries = catalog_entries()
    assert len(entries) == 28
    calm = next(e for e in entries if e["code"] == "calm_ambient_01")
    assert calm["listen_summary"]
    assert "mean_loudness=" in calm["listen_summary"]
    notes = listen_notes_for_code("timing")
    assert notes is not None
    assert notes.get("objective", {}).get("mean_volume_db") is not None
    listen_blob = json.dumps(notes.get("listen") or {}).lower()
    assert "432" not in listen_blob


def test_selector_prompt_includes_wound_labels_and_listen_notes() -> None:
    from tts_pipeline.background_policy.selection import build_selector_prompts

    system, user = build_selector_prompts(
        content_text="The tools keep changing faster than you can learn.",
        title="WK-06 Age / Tech Obsolescence",
        content_type="guided_meditation",
        generation_code="gen_x",
        wound_id="wk_06",
        stage_no=3,
        pillar_code="p05",
        preferred_codes=["timing", "earth", "frozen_in_time"],
        avoid_codes=["blossom", "peaceful_sleep"],
    )
    assert "bg-select-v3" in system
    assert "PREFERRED" in system
    assert "Cognitive Clarity" in user or "p05" in user
    assert "timing" in user
    assert "mean_loudness=" in user or "fingerprint=" in user
    assert "peaceful_sleep" in user


def test_affinity_rail_snaps_avoided_pick_for_wk06_p05() -> None:
    from tts_pipeline.background_policy.affinity import affinity_for_brief, apply_affinity_rail

    rail = affinity_for_brief(pillar_code="p05", wound_id="wk_06")
    assert "timing" in rail["preferred"]
    assert "peaceful_sleep" in rail["avoid"]
    code, note = apply_affinity_rail(
        "peaceful_sleep",
        pillar_code="p05",
        wound_id="wk_06",
    )
    assert code == rail["preferred"][0]
    assert note and "replaced avoided" in note


def test_create_background_selection_applies_rail(monkeypatch: pytest.MonkeyPatch) -> None:
    from tts_pipeline.background_policy import selection as selection_mod

    class _FakeClient:
        model = "gpt-4o-mini"

        def select_background(self, **kwargs):
            assert "timing" in (kwargs.get("preferred_codes") or [])
            return {
                "selected_code": "peaceful_sleep",  # avoided for p05/wk_06
                "reason": "sleep vibe",
                "alternatives": [
                    {"code": "timing", "reason": "alt"},
                    {"code": "earth", "reason": "alt2"},
                    {"code": "pure_ambient", "reason": "alt3"},
                ],
            }

    picked = selection_mod.create_background_selection(
        content_text="Tools move faster than you can learn at work.",
        title="WK-06",
        generation_code="gen_x",
        wound_id="wk_06",
        stage_no=3,
        pillar_code="p05",
        client=_FakeClient(),
    )
    assert picked["selected_code"] == "timing"
    assert picked["selected_by"] == "openai_affinity_rail"
    assert picked["affinity"]["rail_note"]
