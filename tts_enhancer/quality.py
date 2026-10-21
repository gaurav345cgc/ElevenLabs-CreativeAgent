"""Quality heuristics for enhanced narration output."""

from __future__ import annotations

from transcript_composer.duration import count_words
from tts_enhancer.exceptions import EnhancementQualityError


def validate_enhanced_output(*, raw_text: str, enhanced_text: str) -> None:
    if not enhanced_text.strip():
        raise EnhancementQualityError("enhanced output is empty")

    raw_words = count_words(raw_text)
    enhanced_words = count_words(enhanced_text)
    if raw_words >= 20 and enhanced_words < int(raw_words * 0.5):
        raise EnhancementQualityError(
            f"enhanced output too short ({enhanced_words} words vs {raw_words} raw words)"
        )
