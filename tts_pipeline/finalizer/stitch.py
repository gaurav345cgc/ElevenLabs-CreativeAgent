"""Merge completed chunk MP3s into one final narration file."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from tts_pipeline.finalizer.silence import generate_silence_mp3


class FinalMergeError(RuntimeError):
    """Chunk MP3s could not be merged into final output."""


MergeFn = Callable[[list[bytes]], bytes]
HoldSpec = tuple[int, int]  # (after_chunk_index, hold_seconds)

DEFAULT_EDGE_FADE_MS = 100


def apply_edge_fade(
    mp3_bytes: bytes,
    *,
    fade_in: bool,
    fade_out: bool,
    fade_ms: int = DEFAULT_EDGE_FADE_MS,
    ffmpeg_executable: str | None = None,
    audio_bitrate: str = "128k",
) -> bytes:
    """Apply a short fade at the head and/or tail of one chunk's audio.

    Removes the hard "edit" click where a speech chunk meets a silence hold.
    Fade-out uses the reverse/fade-in/reverse trick so it never needs to probe
    the clip's exact duration.
    """
    if not fade_in and not fade_out:
        return mp3_bytes
    if fade_ms <= 0:
        return mp3_bytes

    fade_seconds = fade_ms / 1000.0
    filters: list[str] = []
    if fade_in:
        filters.append(f"afade=t=in:d={fade_seconds}")
    if fade_out:
        filters.append(f"afade=t=in:d={fade_seconds},areverse,afade=t=in:d={fade_seconds},areverse")
    audio_filter = ",".join(filters)

    ffmpeg = ffmpeg_executable or resolve_ffmpeg_executable()
    with tempfile.TemporaryDirectory(prefix="tts-edge-fade-") as tmp_dir:
        work = Path(tmp_dir)
        input_path = work / "in.mp3"
        output_path = work / "out.mp3"
        input_path.write_bytes(mp3_bytes)

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-af",
            audio_filter,
            "-c:a",
            "libmp3lame",
            "-b:a",
            audio_bitrate,
            str(output_path),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise FinalMergeError(f"ffmpeg edge fade failed: {stderr or exc}") from exc
        except FileNotFoundError as exc:
            raise FinalMergeError(f"ffmpeg executable not found: {ffmpeg}") from exc

        if not output_path.is_file():
            raise FinalMergeError("ffmpeg edge fade produced no output file")

        payload = output_path.read_bytes()
        if not payload:
            raise FinalMergeError("ffmpeg edge fade produced an empty output file")
        return payload


def resolve_ffmpeg_executable() -> str:
    import os

    override = os.environ.get("CREATIVE_AGENT_FFMPEG_PATH", "").strip()
    if override:
        return override
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise FinalMergeError(
        "ffmpeg not found on PATH. Install ffmpeg or set CREATIVE_AGENT_FFMPEG_PATH."
    )


def merge_mp3_chunks(
    chunk_bytes: list[bytes],
    *,
    ffmpeg_executable: str | None = None,
    audio_bitrate: str = "128k",
) -> bytes:
    """Concatenate MP3 chunks with ffmpeg re-encode for clean joins."""
    if not chunk_bytes:
        raise FinalMergeError("merge_mp3_chunks requires at least one chunk")

    ffmpeg = ffmpeg_executable or resolve_ffmpeg_executable()

    with tempfile.TemporaryDirectory(prefix="tts-final-merge-") as tmp_dir:
        work = Path(tmp_dir)
        filelist_lines: list[str] = []
        for index, payload in enumerate(chunk_bytes):
            chunk_path = work / f"chunk_{index:04d}.mp3"
            chunk_path.write_bytes(payload)
            filelist_lines.append(f"file '{chunk_path.name}'")

        filelist_path = work / "filelist.txt"
        filelist_path.write_text("\n".join(filelist_lines) + "\n", encoding="utf-8")
        output_path = work / "final.mp3"

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(filelist_path),
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
                cwd=work,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise FinalMergeError(f"ffmpeg merge failed: {stderr or exc}") from exc
        except FileNotFoundError as exc:
            raise FinalMergeError(f"ffmpeg executable not found: {ffmpeg}") from exc

        if not output_path.is_file():
            raise FinalMergeError("ffmpeg merge produced no output file")

        return output_path.read_bytes()


def merge_mp3_chunks_with_holds(
    chunk_bytes: list[bytes],
    holds: list[HoldSpec],
    *,
    ffmpeg_executable: str | None = None,
    audio_bitrate: str = "128k",
    silence_cache: dict[int, bytes] | None = None,
    edge_fade_ms: int = DEFAULT_EDGE_FADE_MS,
) -> bytes:
    """Concatenate speech chunks with silence inserted after selected indexes.

    ``holds`` entries are ``(after_chunk_index, hold_seconds)``. Multiple holds for
    the same index are inserted in the order provided.

    Only chunks directly adjacent to a hold get a short edge fade (tail of the
    chunk before it, head of the chunk after it) — this removes the hard cut
    into/out of digital silence without touching mid-flow chunk boundaries that
    have no hold between them.
    """
    if not chunk_bytes:
        raise FinalMergeError("merge_mp3_chunks_with_holds requires at least one chunk")

    if not holds:
        return merge_mp3_chunks(
            chunk_bytes,
            ffmpeg_executable=ffmpeg_executable,
            audio_bitrate=audio_bitrate,
        )

    chunk_count = len(chunk_bytes)
    for after_chunk_index, hold_seconds in holds:
        if after_chunk_index < 0 or after_chunk_index >= chunk_count:
            raise FinalMergeError(
                f"after_chunk_index {after_chunk_index} out of range for "
                f"{chunk_count} chunks"
            )
        if hold_seconds < 1:
            raise FinalMergeError(f"hold_seconds must be >= 1, got {hold_seconds}")

    holds_by_index: dict[int, list[int]] = {}
    for after_chunk_index, hold_seconds in holds:
        holds_by_index.setdefault(after_chunk_index, []).append(hold_seconds)

    ffmpeg = ffmpeg_executable or resolve_ffmpeg_executable()
    faded_chunk_bytes = list(chunk_bytes)
    for after_chunk_index in holds_by_index:
        faded_chunk_bytes[after_chunk_index] = apply_edge_fade(
            faded_chunk_bytes[after_chunk_index],
            fade_in=False,
            fade_out=True,
            fade_ms=edge_fade_ms,
            ffmpeg_executable=ffmpeg,
            audio_bitrate=audio_bitrate,
        )
        next_index = after_chunk_index + 1
        if next_index < chunk_count:
            faded_chunk_bytes[next_index] = apply_edge_fade(
                faded_chunk_bytes[next_index],
                fade_in=True,
                fade_out=False,
                fade_ms=edge_fade_ms,
                ffmpeg_executable=ffmpeg,
                audio_bitrate=audio_bitrate,
            )

    cache = silence_cache if silence_cache is not None else {}
    media: list[bytes] = []
    for index, payload in enumerate(faded_chunk_bytes):
        media.append(payload)
        for hold_seconds in holds_by_index.get(index, []):
            media.append(
                generate_silence_mp3(
                    hold_seconds,
                    ffmpeg_executable=ffmpeg,
                    audio_bitrate=audio_bitrate,
                    cache=cache,
                )
            )

    return merge_mp3_chunks(
        media,
        ffmpeg_executable=ffmpeg,
        audio_bitrate=audio_bitrate,
    )
