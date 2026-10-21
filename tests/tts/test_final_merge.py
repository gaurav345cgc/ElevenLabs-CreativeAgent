"""Phase 10: stitch intercalation with silence holds."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

import tts_pipeline.finalizer.stitch as stitch_module
from tts_pipeline.finalizer.silence import generate_silence_mp3
from tts_pipeline.finalizer.stitch import (
    FinalMergeError,
    apply_edge_fade,
    merge_mp3_chunks,
    merge_mp3_chunks_with_holds,
)


def _generate_tone_mp3(duration_seconds: int = 1) -> bytes:
    """Non-silent stand-in audio — fading actual digital silence is a no-op."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg not on PATH")
    with tempfile.TemporaryDirectory(prefix="tts-tone-") as tmp_dir:
        output_path = Path(tmp_dir) / "tone.mp3"
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:duration={duration_seconds}",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return output_path.read_bytes()


def _ffprobe_duration(payload: bytes) -> float:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        pytest.skip("ffprobe not on PATH")
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
        handle.write(payload)
        path = handle.name
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_merge_with_holds_adds_silence_duration() -> None:
    speech0 = generate_silence_mp3(1)  # stand-in speech chunk
    speech1 = generate_silence_mp3(1)
    speech_only = merge_mp3_chunks([speech0, speech1])
    with_hold = merge_mp3_chunks_with_holds([speech0, speech1], holds=[(0, 5)])

    speech_duration = _ffprobe_duration(speech_only)
    held_duration = _ffprobe_duration(with_hold)
    assert abs(held_duration - (speech_duration + 5.0)) <= 0.35


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_empty_holds_matches_plain_merge_path() -> None:
    speech0 = generate_silence_mp3(1)
    speech1 = generate_silence_mp3(1)
    plain = merge_mp3_chunks([speech0, speech1])
    via_holds = merge_mp3_chunks_with_holds([speech0, speech1], holds=[])
    assert via_holds == plain


def test_rejects_out_of_range_chunk_index() -> None:
    with pytest.raises(FinalMergeError, match="out of range"):
        merge_mp3_chunks_with_holds([b"a", b"b"], holds=[(2, 3)])


def test_rejects_empty_chunk_list() -> None:
    with pytest.raises(FinalMergeError, match="at least one chunk"):
        merge_mp3_chunks_with_holds([], holds=[(0, 3)])


def test_apply_edge_fade_is_noop_without_fade_flags() -> None:
    payload = b"not-really-mp3-bytes"
    assert apply_edge_fade(payload, fade_in=False, fade_out=False) == payload


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_apply_edge_fade_changes_bytes() -> None:
    payload = _generate_tone_mp3(1)
    faded = apply_edge_fade(payload, fade_in=True, fade_out=True, fade_ms=100)
    assert faded != payload


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_merge_with_holds_only_fades_chunks_adjacent_to_a_hold(monkeypatch) -> None:
    calls: list[tuple[bool, bool]] = []

    def spy_apply_edge_fade(payload, *, fade_in, fade_out, **_kwargs):
        calls.append((fade_in, fade_out))
        return payload

    monkeypatch.setattr(stitch_module, "apply_edge_fade", spy_apply_edge_fade)

    chunks = [generate_silence_mp3(1) for _ in range(4)]
    merge_mp3_chunks_with_holds(chunks, holds=[(0, 5)])

    # Only chunk 0 (tail) and chunk 1 (head) are adjacent to the single hold
    # after chunk 0 — chunks 2 and 3 must never be touched.
    assert calls == [(False, True), (True, False)]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_merge_with_hold_on_last_chunk_only_fades_tail(monkeypatch) -> None:
    calls: list[tuple[bool, bool]] = []

    def spy_apply_edge_fade(payload, *, fade_in, fade_out, **_kwargs):
        calls.append((fade_in, fade_out))
        return payload

    monkeypatch.setattr(stitch_module, "apply_edge_fade", spy_apply_edge_fade)

    chunks = [generate_silence_mp3(1), generate_silence_mp3(1)]
    merge_mp3_chunks_with_holds(chunks, holds=[(1, 5)])

    # No chunk after the last one, so only a tail fade is applied.
    assert calls == [(False, True)]
