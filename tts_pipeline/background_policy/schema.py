"""Background profile schema and mix bounds for post-TTS bed mixing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BackgroundProfile:
    """Approved background bed profile with ffmpeg mix parameters."""

    code: str
    display_name: str
    description: str
    track_object_key: str
    gain_db: float = -30.0
    fade_in_ms: int = 3000
    fade_out_ms: int = 5000
    tail_padding_ms: int = 4000
    duck: bool = False
    duck_threshold: float = 0.03
    duck_ratio: float = 8.0
    duck_attack_ms: int = 5
    duck_release_ms: int = 400
    loudness_target_lufs: float = -16.0
    loudness_true_peak_db: float = -1.5
    output_bitrate: str = "192k"
    start_delay_ms: int = 6000

    # Optional signature open/close bell — plays inside the existing quiet windows
    # (start_delay_ms before the bed fades in; tail_padding_ms after narration ends).
    # None means "no chime" — zero behavior change for profiles that don't set these.
    intro_chime_object_key: str | None = None
    outro_chime_object_key: str | None = None
    chime_gain_db: float = -12.0