"""Session theme expansion — title/wound/pillar → spoken-script requirements."""

from __future__ import annotations

import re

from models.requests import CreateTranscriptRequest
from transcript_composer.title import GENERATION_DISPLAY, WOUND_DISPLAY

PILLAR_DISPLAY: dict[str, str] = {
    "p01": "Mindful Awareness",
    "p02": "Emotional Regulation",
    "p03": "Somatic Healing",
    "p04": "Deep Rest & Sleep",
    "p05": "Cognitive Clarity",
    "p06": "Relational Wellbeing",
    "p07": "Spiritual Inquiry",
    "p12": "Generativity",
}

# Situational frames from product titles (WK / PH / FR overlays).
_THEME_FRAMES: tuple[tuple[re.Pattern[str], str, tuple[str, ...]], ...] = (
    (
        re.compile(
            r"\b(work|workplace|organis|organiz|career|job|office|colleague|employer|"
            r"betrayal|purpose at work)\b",
            re.IGNORECASE,
        ),
        (
            "Frame this session in WORK / professional life "
            "(the job, workplace, role, colleagues, or career pressure). "
            "A generic calm meditation with no work context is a failure."
        ),
        (
            "work",
            "job",
            "workplace",
            "office",
            "career",
            "colleague",
            "colleagues",
            "boss",
            "employer",
            "team",
            "desk",
            "meeting",
            "shift",
            "role",
        ),
    ),
    (
        re.compile(
            r"\b(pain|chronic pain|fatigue|burnout|body|physical|ache|exhaust)\b",
            re.IGNORECASE,
        ),
        (
            "Frame this session in PHYSICAL experience "
            "(pain, fatigue, burnout held in the body). "
            "Name the bodily theme gently; do not lecture about medical conditions."
        ),
        (
            "pain",
            "body",
            "bodies",
            "fatigue",
            "burnout",
            "exhaust",
            "ache",
            "aching",
            "sore",
            "tension",
            "muscle",
            "muscles",
            "physical",
        ),
    ),
    (
        re.compile(r"\b(friend|friendship|lonely|loneliness|belonging)\b", re.IGNORECASE),
        (
            "Frame this session in FRIENDSHIP / social connection / loneliness. "
            "A generic meditation with no relational friendship context is a failure."
        ),
        (
            "friend",
            "friends",
            "friendship",
            "lonely",
            "loneliness",
            "alone",
            "connection",
            "belong",
            "belonging",
            "people",
        ),
    ),
)


def wound_label(wound_id: str | None) -> str:
    key = (wound_id or "").strip().lower()
    return WOUND_DISPLAY.get(key, key.replace("_", " ") or "this struggle")


def pillar_label(pillar_code: str | None) -> str | None:
    if not pillar_code:
        return None
    key = pillar_code.strip().lower()
    return PILLAR_DISPLAY.get(key, key.upper())


def generation_label(generation_code: str | None) -> str:
    key = (generation_code or "").strip().lower()
    return GENERATION_DISPLAY.get(key, key.replace("_", " ") or "the listener")


def session_title(request: CreateTranscriptRequest) -> str:
    if request.title_hint and request.title_hint.strip():
        # Drop sample suffix for theme language (" — sample A")
        title = request.title_hint.strip()
        title = re.sub(r"\s*[—\-–]\s*sample\s+[A-Z]\s*$", "", title, flags=re.IGNORECASE)
        return title[:512]
    return f"{wound_label(request.wound_id)} meditation"


def detect_theme_frame(title: str) -> tuple[str, tuple[str, ...]] | None:
    for pattern, guidance, keywords in _THEME_FRAMES:
        if pattern.search(title):
            return guidance, keywords
    return None


def required_theme_keywords(request: CreateTranscriptRequest) -> tuple[str, ...] | None:
    frame = detect_theme_frame(session_title(request))
    if frame is None:
        return None
    return frame[1]


def format_session_theme_block(request: CreateTranscriptRequest) -> str:
    """Prompt block: human theme the spoken script must honor."""
    title = session_title(request)
    wound = wound_label(request.wound_id)
    pillar = pillar_label(request.pillar_code)
    generation = generation_label(request.generation_code)
    frame = detect_theme_frame(title)
    frame_line = frame[0] if frame else (
        "Stay faithful to the wound theme in human language — "
        "not a generic wellness script that could belong to any title."
    )
    pillar_line = f"- Pillar (feel, do not say the code): {pillar}" if pillar else "- Pillar: (none)"

    return f"""## Session theme (must shape the spoken script)
- Session title / intent: {title}
- Wound in human language: {wound} (internal code {request.wound_id} — never speak codes)
{pillar_line}
- Generation register: {generation}
- Situational frame: {frame_line}

Hard requirements:
1. OPENING must name this session's purpose in plain speech that matches the title
   (if the title is about work, mention work/the job/the workplace gently in the welcome).
2. mind_heart and closing must return to that same life theme — not only generic peace.
3. settling / body / breath stay somatic, but may briefly acknowledge the theme
   (e.g. tension carried from work, pain in the body, missing a friend).
4. Never speak product codes, wound codes, or pillar codes (WK-04, PH-01, gx_04, P04, etc.).
5. Do not invent a different topic than the title — the listener chose this theme."""
