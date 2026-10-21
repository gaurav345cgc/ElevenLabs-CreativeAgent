"""Phase 9: silence MP3 generator tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tts_pipeline.finalizer import silence as silence_module
from tts_pipeline.finalizer.silence import SilenceGenerationError, generate_silence_mp3
from tts_pipeline.pause_planner.policy import MAX_HOLD_SECONDS


def test_duration_below_one_raises() -> None:
    with pytest.raises(SilenceGenerationError, match=">= 1"):
        generate_silence_mp3(0)


def test_duration_above_max_raises() -> None:
    with pytest.raises(SilenceGenerationError, match="MAX_HOLD_SECONDS"):
        generate_silence_mp3(MAX_HOLD_SECONDS + 1)


def test_cache_avoids_second_ffmpeg_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    monkeypatch.setattr(
        "tts_pipeline.finalizer.stitch.resolve_ffmpeg_executable",
        lambda: "ffmpeg",
    )

    def fake_run(command, **kwargs):
        calls["n"] += 1
        Path(command[-1]).write_bytes(b"silence-bytes")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(silence_module.subprocess, "run", fake_run)

    cache: dict[int, bytes] = {}
    first = generate_silence_mp3(3, cache=cache)
    second = generate_silence_mp3(3, cache=cache)
    assert first == b"silence-bytes"
    assert second == first
    assert calls["n"] == 1
    assert cache[3] == first


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_generate_three_second_silence_smoke() -> None:
    payload = generate_silence_mp3(3)
    assert payload
    assert len(payload) > 100

    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        pytest.skip("ffprobe not on PATH")

    import tempfile

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
        duration = float(result.stdout.strip())
    finally:
        Path(path).unlink(missing_ok=True)

    assert abs(duration - 3.0) <= 0.15
