"""Catalog bed selection (OpenAI + reviewer) tests."""

from __future__ import annotations

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
