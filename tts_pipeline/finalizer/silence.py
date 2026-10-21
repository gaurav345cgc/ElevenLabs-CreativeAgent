"""Generate silent MP3 bytes for pause intercalation at stitch time."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from tts_pipeline.pause_planner.policy import MAX_HOLD_SECONDS

DEFAULT_SILENCE_BITRATE = "128k"
DEFAULT_SAMPLE_RATE = 44100
DEFAULT_CHANNEL_LAYOUT = "mono"


class SilenceGenerationError(RuntimeError):
    """Silent MP3 could not be generated."""


def generate_silence_mp3(
    duration_seconds: int,
    *,
    ffmpeg_executable: str | None = None,
    audio_bitrate: str = DEFAULT_SILENCE_BITRATE,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channel_layout: str = DEFAULT_CHANNEL_LAYOUT,
    cache: dict[int, bytes] | None = None,
) -> bytes:
    """Return MP3 bytes of silence lasting ``duration_seconds``.

    Optional ``cache`` maps duration → bytes for reuse within one stitch invocation.
    """
    if duration_seconds < 1:
        raise SilenceGenerationError("duration_seconds must be >= 1")
    if duration_seconds > MAX_HOLD_SECONDS:
        raise SilenceGenerationError(
            f"duration_seconds {duration_seconds} exceeds MAX_HOLD_SECONDS={MAX_HOLD_SECONDS}"
        )

    if cache is not None and duration_seconds in cache:
        return cache[duration_seconds]

    from tts_pipeline.finalizer.stitch import resolve_ffmpeg_executable

    ffmpeg = ffmpeg_executable or resolve_ffmpeg_executable()
    with tempfile.TemporaryDirectory(prefix="tts-silence-") as tmp_dir:
        output_path = Path(tmp_dir) / f"silence_{duration_seconds:03d}.mp3"
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={sample_rate}:cl={channel_layout}",
            "-t",
            str(duration_seconds),
            "-c:a",
            "libmp3lame",
            "-b:a",
            audio_bitrate,
            str(output_path),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise SilenceGenerationError(
                f"ffmpeg silence generation failed: {stderr or exc}"
            ) from exc
        except FileNotFoundError as exc:
            raise SilenceGenerationError(f"ffmpeg executable not found: {ffmpeg}") from exc

        if not output_path.is_file():
            raise SilenceGenerationError("ffmpeg silence generation produced no output file")

        payload = output_path.read_bytes()
        if not payload:
            raise SilenceGenerationError("ffmpeg silence generation produced empty output")

    if cache is not None:
        cache[duration_seconds] = payload
    return payload
