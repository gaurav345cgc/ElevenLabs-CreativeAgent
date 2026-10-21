"""Theme brief helpers for Agent 1."""

from __future__ import annotations

from models.requests import CreateTranscriptRequest
from transcript_composer.theme import (
    detect_theme_frame,
    format_session_theme_block,
    required_theme_keywords,
    session_title,
)


def test_work_title_requires_work_keywords() -> None:
    req = CreateTranscriptRequest(
        tenant_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        content_type="guided_meditation",
        generation_code="gen_x",
        wound_id="gx_04",
        stage_no=2,
        target_duration_minutes=10,
        pillar_code="p04",
        title_hint="WK-04 Organisational Betrayal — sample A",
    )
    keys = required_theme_keywords(req)
    assert keys is not None
    assert "work" in keys or "job" in keys
    assert "WORK" in format_session_theme_block(req).upper()
    assert "sample" not in session_title(req).lower()


def test_generic_title_has_no_situational_keywords() -> None:
    req = CreateTranscriptRequest(
        tenant_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        content_type="guided_meditation",
        generation_code="millennial",
        wound_id="ml_02",
        stage_no=2,
        target_duration_minutes=5,
        pillar_code="p04",
    )
    assert required_theme_keywords(req) is None
    assert detect_theme_frame(session_title(req)) is None
