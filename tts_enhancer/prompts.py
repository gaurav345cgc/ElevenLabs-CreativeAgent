"""Load Agent 2 enhancement guide for the Script Doctor system prompt."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_GUIDE_PATH = Path(__file__).resolve().parents[1] / "guide" / "Agent2-guide.md"
_FOOTNOTE_PATTERN = re.compile(r"\[\^\d+\]")

SYSTEM_PROMPT_HEADER = """You are Agent 2 — ElevenLabs Script Doctor.

Your job is to rewrite meditation narration from Agent 1 (Pattern Transcript Composer) into \
TTS-ready text for ElevenLabs. Follow the authoritative enhancement guide below **strictly**.

Hard rules (never violate):
1. Preserve Agent 1's therapeutic intent and emotional register — improve speakability only.
2. Do not add new practices, themes, or instructions that were not in the source.
3. Do not add length. You MAY drop near-duplicate / paraphrased restatements that say the same \
cue twice; keep every distinct piece of guidance.
4. Output spoken narration only — no labels, markdown headings, pattern names, or meta-commentary.
5. Do not include stage directions like "(pause 4 seconds)" or "she whispers calmly".
6. Keep each sentence group on its own line; use a blank line between beats.
7. Beat density for realistic pacing: each beat must be at most 1–3 short sentences \
(prefer 1 sentence per beat). Never pack 4+ sentences into one beat — silence holds are \
inserted between beats downstream.
8. Preserve the arc: a brief welcome/intro first, then the main practice. Do not merge the opening \
into a long wall of continuous instruction; keep the intro short and clearly hand off into settling/body.
9. Consumer ear: lean and clear. Prefer fewer words over soft padding.
"""


@lru_cache(maxsize=1)
def load_agent2_guide_text() -> str:
    """Return Agent2-guide.md with footnote markers stripped."""
    raw = _GUIDE_PATH.read_text(encoding="utf-8")
    return _FOOTNOTE_PATTERN.sub("", raw).strip()


def build_system_prompt() -> str:
    guide = load_agent2_guide_text()
    return f"{SYSTEM_PROMPT_HEADER}\n\n# Enhancement guide (follow strictly)\n\n{guide}"
