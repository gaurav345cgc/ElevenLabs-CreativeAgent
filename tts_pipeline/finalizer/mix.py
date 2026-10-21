"""Mix a curated background bed under narration into a single master MP3."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from tts_pipeline.background_policy.schema import BackgroundProfile
from tts_pipeline.finalizer.stitch import resolve_ffmpeg_executable

logger = logging.getLogger("creative_agent.tts.mix")

_DURATION_FROM_FFMPEG_RE = re.compile(
    r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


class BackgroundMixError(RuntimeError):
    """Narration and background bed could not be mixed into a master file."""


MixFn = Callable[[bytes, bytes, BackgroundProfile], bytes]


def _resolve_ffprobe_executable(ffmpeg_executable: str) -> str | None:
    """Best-effort ffprobe lookup — sibling of ffmpeg, then PATH."""
    import os

    override = os.environ.get("CREATIVE_AGENT_FFPROBE_PATH", "").strip()
    if override:
        return override

    sibling = Path(ffmpeg_executable).with_name(
        "ffprobe" + Path(ffmpeg_executable).suffix
    )
    if sibling.is_file():
        return str(sibling)

    return shutil.which("ffprobe")


def _probe_duration_seconds(ffprobe: str | None, media_path: Path) -> float | None:
    if not ffprobe:
        return None
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    raw = (result.stdout or "").strip()
    try:
        return float(raw)
    except ValueError:
        return None


def _duration_from_ffmpeg_i(ffmpeg: str, media_path: Path) -> float | None:
    """Parse ``Duration:`` from ``ffmpeg -i`` stderr (no ffprobe required)."""
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(media_path)],
            check=False,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    stderr = getattr(result, "stderr", None) or ""
    match = _DURATION_FROM_FFMPEG_RE.search(stderr)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return (int(hours) * 3600) + (int(minutes) * 60) + float(seconds)


def _estimate_mp3_duration_seconds(byte_size: int, *, bitrate_kbps: int = 128) -> float:
    """Rough CBR duration estimate — last-resort bound so bed loop cannot run forever."""
    if byte_size <= 0 or bitrate_kbps <= 0:
        return 60.0
    return max(1.0, (byte_size * 8.0) / (bitrate_kbps * 1000.0))


def _resolve_narration_duration_seconds(
    *,
    ffmpeg: str,
    ffprobe: str | None,
    narration_path: Path,
    narration_bytes: bytes,
) -> float:
    duration = _probe_duration_seconds(ffprobe, narration_path)
    if duration is not None and duration > 0:
        return duration
    duration = _duration_from_ffmpeg_i(ffmpeg, narration_path)
    if duration is not None and duration > 0:
        logger.warning("ffprobe unavailable; using ffmpeg -i duration=%.2fs", duration)
        return duration
    estimated = _estimate_mp3_duration_seconds(len(narration_bytes))
    logger.warning(
        "duration probe failed; estimating narration=%.2fs from byte size (prevents infinite bed loop)",
        estimated,
    )
    return estimated


def _build_filter_complex(
    profile: BackgroundProfile,
    *,
    fade_out_start_s: float | None,
    intro_chime_input_index: int | None = None,
    outro_chime_input_index: int | None = None,
    outro_chime_delay_ms: int = 0,
) -> str:
    fade_in_s = profile.fade_in_ms / 1000.0
    fade_out_s = profile.fade_out_ms / 1000.0
    tail_s = profile.tail_padding_ms / 1000.0

    # Bed: level it under the voice and fade it in from silence.
    bed_chain = f"[1:a]volume={profile.gain_db}dB,afade=t=in:st=0:d={fade_in_s}[bed]"
    chains = [bed_chain]

    if profile.duck:
        # We need two copies of the voice stream (one for compressor, one for mixing).
        if profile.start_delay_ms > 0:
            voice_chain = f"[0:a]adelay={profile.start_delay_ms}:all=1,asplit=2[voice_compress][voice_mix]"
        else:
            voice_chain = "[0:a]asplit=2[voice_compress][voice_mix]"

        duck_chain = (
            f"[bed][voice_compress]sidechaincompress="
            f"threshold={profile.duck_threshold}:ratio={profile.duck_ratio}:"
            f"attack={profile.duck_attack_ms}:release={profile.duck_release_ms}[ducked]"
        )
        chains += [voice_chain, duck_chain]
        mix_refs = ["[voice_mix]", "[ducked]"]
    else:
        # No ducking, so we only need one copy of the voice stream.
        if profile.start_delay_ms > 0:
            voice_chain = f"[0:a]adelay={profile.start_delay_ms}:all=1[voice_mix]"
            voice_ref_mix = "[voice_mix]"
            chains.append(voice_chain)
        else:
            voice_ref_mix = "[0:a]"
        mix_refs = [voice_ref_mix, "[bed]"]

    # Optional signature bell — plays inside the existing quiet windows (intro at
    # t=0 alongside the bed fade-in, outro delayed to land in the tail padding).
    if intro_chime_input_index is not None:
        chains.append(f"[{intro_chime_input_index}:a]volume={profile.chime_gain_db}dB[introchime]")
        mix_refs.append("[introchime]")
    if outro_chime_input_index is not None:
        chains.append(
            f"[{outro_chime_input_index}:a]adelay={outro_chime_delay_ms}:all=1,"
            f"volume={profile.chime_gain_db}dB[outrochime]"
        )
        mix_refs.append("[outrochime]")

    mix_chain = f"{''.join(mix_refs)}amix=inputs={len(mix_refs)}:duration=longest:dropout_transition=0[mixed]"
    chains.append(mix_chain)
    graph_prefix = ";".join(chains)

    # Tail padding lets the bed breathe after the last spoken word, then fade + loudnorm.
    tail_filters = [f"apad=pad_dur={tail_s}"]
    if fade_out_start_s is not None and fade_out_start_s > 0:
        tail_filters.append(f"afade=t=out:st={fade_out_start_s}:d={fade_out_s}")
    tail_filters.append(
        f"loudnorm=I={profile.loudness_target_lufs}:TP={profile.loudness_true_peak_db}:LRA=11"
    )
    out_chain = "[mixed]" + ",".join(tail_filters) + "[out]"

    return f"{graph_prefix};{out_chain}"


def mix_background(
    narration_bytes: bytes,
    bed_bytes: bytes,
    profile: BackgroundProfile,
    *,
    ffmpeg_executable: str | None = None,
    intro_chime_bytes: bytes | None = None,
    outro_chime_bytes: bytes | None = None,
) -> bytes:
    """Mix ``bed_bytes`` under ``narration_bytes`` per ``profile`` and return MP3 bytes.

    ``intro_chime_bytes``/``outro_chime_bytes`` are optional short bell/chime clips —
    only used when provided (independent of whether ``profile`` has chime object keys
    set; callers resolve those to bytes upstream).
    """
    if not narration_bytes:
        raise BackgroundMixError("mix_background requires non-empty narration audio")
    if not bed_bytes:
        raise BackgroundMixError("mix_background requires non-empty background bed audio")

    ffmpeg = ffmpeg_executable or resolve_ffmpeg_executable()
    ffprobe = _resolve_ffprobe_executable(ffmpeg)

    with tempfile.TemporaryDirectory(prefix="tts-background-mix-") as tmp_dir:
        work = Path(tmp_dir)
        narration_path = work / "narration.mp3"
        bed_path = work / "background.mp3"
        output_path = work / "master.mp3"
        narration_path.write_bytes(narration_bytes)
        bed_path.write_bytes(bed_bytes)

        # ALWAYS set -t when looping the bed. Missing duration previously caused
        # Lambda 900s timeouts (infinite encode with -stream_loop -1).
        narration_duration = _resolve_narration_duration_seconds(
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            narration_path=narration_path,
            narration_bytes=narration_bytes,
        )
        total_duration = (
            narration_duration
            + (profile.start_delay_ms / 1000.0)
            + (profile.tail_padding_ms / 1000.0)
        )
        fade_out_start_s = max(0.0, total_duration - profile.fade_out_ms / 1000.0)

        input_args: list[str] = ["-i", str(narration_path), "-stream_loop", "-1", "-i", str(bed_path)]
        next_input_index = 2
        intro_chime_input_index: int | None = None
        outro_chime_input_index: int | None = None

        if intro_chime_bytes:
            intro_chime_path = work / "intro_chime.mp3"
            intro_chime_path.write_bytes(intro_chime_bytes)
            input_args += ["-i", str(intro_chime_path)]
            intro_chime_input_index = next_input_index
            next_input_index += 1

        if outro_chime_bytes:
            outro_chime_path = work / "outro_chime.mp3"
            outro_chime_path.write_bytes(outro_chime_bytes)
            input_args += ["-i", str(outro_chime_path)]
            outro_chime_input_index = next_input_index
            next_input_index += 1

        # Outro chime lands right where narration ends: start_delay (voice's own
        # offset) + how long the voice actually ran.
        outro_chime_delay_ms = profile.start_delay_ms + int(narration_duration * 1000)

        filter_complex = _build_filter_complex(
            profile,
            fade_out_start_s=fade_out_start_s,
            intro_chime_input_index=intro_chime_input_index,
            outro_chime_input_index=outro_chime_input_index,
            outro_chime_delay_ms=outro_chime_delay_ms,
        )

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *input_args,
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-c:a",
            "libmp3lame",
            "-b:a",
            profile.output_bitrate,
            "-t",
            f"{total_duration:.2f}",
            str(output_path),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                cwd=work,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise BackgroundMixError(f"ffmpeg background mix failed: {stderr or exc}") from exc
        except FileNotFoundError as exc:
            raise BackgroundMixError(f"ffmpeg executable not found: {ffmpeg}") from exc

        if not output_path.is_file():
            raise BackgroundMixError("ffmpeg background mix produced no output file")

        master_bytes = output_path.read_bytes()
        if not master_bytes:
            raise BackgroundMixError("ffmpeg background mix produced an empty output file")

        return master_bytes
