"""Approved background bed profiles and mix policy."""

from tts_pipeline.background_policy.affinity import affinity_for_brief, apply_affinity_rail
from tts_pipeline.background_policy.profiles import (
    APPROVED_BACKGROUND_PROFILES,
    DEFAULT_BACKGROUND_PROFILE_CODE,
    catalog_entries,
    display_name_for_code,
    listen_notes_for_code,
    listen_summary_for_code,
)
from tts_pipeline.background_policy.resolver import (
    BackgroundPolicyError,
    get_background_profile,
    list_background_profile_codes,
    resolve_background_profile,
)
from tts_pipeline.background_policy.schema import BackgroundProfile
from tts_pipeline.background_policy.selection import (
    BACKGROUND_PROFILE_CODE_KEY,
    BACKGROUND_SELECTION_KEY,
    apply_reviewer_background_choice,
    copy_background_metadata,
    create_background_selection,
    default_background_selection,
    load_background_selection,
    resolve_bg_selector_mode,
    select_background_for_script,
)

__all__ = [
    "APPROVED_BACKGROUND_PROFILES",
    "BACKGROUND_PROFILE_CODE_KEY",
    "BACKGROUND_SELECTION_KEY",
    "DEFAULT_BACKGROUND_PROFILE_CODE",
    "BackgroundPolicyError",
    "BackgroundProfile",
    "affinity_for_brief",
    "apply_affinity_rail",
    "apply_reviewer_background_choice",
    "catalog_entries",
    "copy_background_metadata",
    "create_background_selection",
    "default_background_selection",
    "display_name_for_code",
    "get_background_profile",
    "list_background_profile_codes",
    "listen_notes_for_code",
    "listen_summary_for_code",
    "load_background_selection",
    "resolve_background_profile",
    "resolve_bg_selector_mode",
    "select_background_for_script",
]
