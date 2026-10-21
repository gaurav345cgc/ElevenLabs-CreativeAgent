"""Voice direction notes derived from script characteristics."""

from __future__ import annotations

import re

INVITE_PATTERN = re.compile(r"\b(let|allow|notice|perhaps|maybe|gently|softly)\b", re.IGNORECASE)
PAUSE_PATTERN = re.compile(r"\b(breath|pause|stillness|rest)\b", re.IGNORECASE)


def build_voice_direction_notes(text: str) -> list[str]:
    notes: list[str] = []
    if INVITE_PATTERN.search(text):
        notes.append("Keep the delivery invitational rather than instructional.")
    if PAUSE_PATTERN.search(text):
        notes.append("Leave gentle space after breath and pause cues.")
    if not notes:
        notes.append("Maintain a calm, steady pace with warm clarity.")
    return notes
