"""Phase 5 — background policy tests."""

from __future__ import annotations

import pytest

from tts_pipeline.background_policy import (
    APPROVED_BACKGROUND_PROFILES,
    DEFAULT_BACKGROUND_PROFILE_CODE,
    BackgroundPolicyError,
    get_background_profile,
    list_background_profile_codes,
    resolve_background_profile,
)
from tts_pipeline.persistence.s3_keys import background_track_key, chime_key


def test_default_profile_exists() -> None:
    assert DEFAULT_BACKGROUND_PROFILE_CODE == "calm_ambient_01"


def test_default_profile_in_approved_registry() -> None:
    assert DEFAULT_BACKGROUND_PROFILE_CODE in APPROVED_BACKGROUND_PROFILES


def test_list_background_profile_codes_is_sorted() -> None:
    codes = list_background_profile_codes()
    assert codes == sorted(codes)
    assert DEFAULT_BACKGROUND_PROFILE_CODE in codes
    assert len(codes) >= 20  # curated library catalog seeded to S3


def test_get_background_profile_returns_expected_track_key() -> None:
    profile = get_background_profile(DEFAULT_BACKGROUND_PROFILE_CODE)
    assert profile.track_object_key == "background/calm_ambient_01.mp3"


def test_unknown_profile_raises_background_policy_error() -> None:
    with pytest.raises(BackgroundPolicyError, match="Unknown background profile"):
        get_background_profile("not_a_profile")


def test_resolve_background_profile_returns_default_for_v1() -> None:
    profile = resolve_background_profile(content_type="meditation", tenant_id=None)
    assert profile.code == DEFAULT_BACKGROUND_PROFILE_CODE


def test_resolve_background_profile_honors_requested_code() -> None:
    profile = resolve_background_profile(requested_code="the_deep")
    assert profile.code == "the_deep"


def test_track_object_key_matches_background_track_key_helper() -> None:
    for code in list_background_profile_codes():
        profile = get_background_profile(code)
        assert profile.track_object_key == background_track_key(code)


def test_default_profile_has_no_chime_configured() -> None:
    # calm_ambient_01 predates the chime fields — must stay a no-op until a chime
    # asset is actually sourced and a profile opts in.
    profile = get_background_profile(DEFAULT_BACKGROUND_PROFILE_CODE)
    assert profile.intro_chime_object_key is None
    assert profile.outro_chime_object_key is None


def test_chime_key_helper_format() -> None:
    assert chime_key("temple_bell_01") == "chimes/temple_bell_01.mp3"
