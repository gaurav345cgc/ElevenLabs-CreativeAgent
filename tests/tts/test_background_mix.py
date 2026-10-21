"""Phase 7 — background mix engine tests."""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
from pathlib import Path

import pytest

from tts_pipeline.background_policy import get_background_profile
from tts_pipeline.finalizer import mix as mix_module
from tts_pipeline.finalizer.mix import (
    BackgroundMixError,
    _build_filter_complex,
    mix_background,
)

PROFILE = get_background_profile("calm_ambient_01")


def test_empty_narration_raises() -> None:
    with pytest.raises(BackgroundMixError, match="narration"):
        mix_background(b"", b"bed-bytes", PROFILE)


def test_empty_bed_raises() -> None:
    with pytest.raises(BackgroundMixError, match="background bed"):
        mix_background(b"narration-bytes", b"", PROFILE)


def test_filter_graph_duck_contains_sidechaincompress() -> None:
    duck_profile = dataclasses.replace(PROFILE, duck=True)
    graph = _build_filter_complex(duck_profile, fade_out_start_s=10.0)
    assert "sidechaincompress" in graph
    assert "loudnorm" in graph
    assert "afade=t=out" in graph


def test_filter_graph_non_duck_omits_sidechaincompress() -> None:
    non_duck = dataclasses.replace(PROFILE, duck=False)
    graph = _build_filter_complex(non_duck, fade_out_start_s=10.0)
    assert "sidechaincompress" not in graph
    assert "amix=inputs=2" in graph


def test_filter_graph_without_duration_omits_fade_out() -> None:
    graph = _build_filter_complex(PROFILE, fade_out_start_s=None)
    assert "afade=t=out" not in graph
    assert "loudnorm" in graph


def test_mix_background_success_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mix_module, "resolve_ffmpeg_executable", lambda: "ffmpeg")
    monkeypatch.setattr(mix_module, "_resolve_ffprobe_executable", lambda _ff: None)
    monkeypatch.setattr(
        mix_module,
        "_resolve_narration_duration_seconds",
        lambda **_kwargs: 12.5,
    )

    captured: list[list[str]] = []

    def fake_run(command, **kwargs):
        captured.append(list(command))
        # ffmpeg writes the master output to the last positional arg (output path).
        Path(command[-1]).write_bytes(b"master-mp3-bytes")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(mix_module.subprocess, "run", fake_run)

    out = mix_background(b"narration", b"bed", PROFILE)
    assert out == b"master-mp3-bytes"
    assert "-t" in captured[0], "must pass -t so looped bed cannot encode forever"
    t_index = captured[0].index("-t")
    assert float(captured[0][t_index + 1]) > 12.0


def test_mix_background_nonzero_exit_raises(monkeypatch) -> None:
    monkeypatch.setattr(mix_module, "resolve_ffmpeg_executable", lambda: "ffmpeg")
    monkeypatch.setattr(mix_module, "_resolve_ffprobe_executable", lambda _ff: None)
    monkeypatch.setattr(
        mix_module,
        "_resolve_narration_duration_seconds",
        lambda **_kwargs: 10.0,
    )

    def fake_run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, output="", stderr="boom")

    monkeypatch.setattr(mix_module.subprocess, "run", fake_run)

    with pytest.raises(BackgroundMixError, match="boom"):
        mix_background(b"narration", b"bed", PROFILE)


def test_mix_background_missing_output_raises(monkeypatch) -> None:
    monkeypatch.setattr(mix_module, "resolve_ffmpeg_executable", lambda: "ffmpeg")
    monkeypatch.setattr(mix_module, "_resolve_ffprobe_executable", lambda _ff: None)

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(mix_module.subprocess, "run", fake_run)

    with pytest.raises(BackgroundMixError, match="no output file"):
        mix_background(b"narration", b"bed", PROFILE)


def test_filter_graph_without_chime_omits_chime_refs() -> None:
    graph = _build_filter_complex(PROFILE, fade_out_start_s=10.0)
    assert "introchime" not in graph
    assert "outrochime" not in graph
    assert "amix=inputs=2" in graph


def test_filter_graph_includes_intro_chime_chain() -> None:
    graph = _build_filter_complex(PROFILE, fade_out_start_s=10.0, intro_chime_input_index=2)
    assert "[2:a]" in graph
    assert "introchime" in graph
    assert "amix=inputs=3" in graph


def test_filter_graph_includes_outro_chime_chain_with_delay() -> None:
    graph = _build_filter_complex(
        PROFILE,
        fade_out_start_s=10.0,
        outro_chime_input_index=2,
        outro_chime_delay_ms=45000,
    )
    assert "[2:a]" in graph
    assert "outrochime" in graph
    assert "adelay=45000:all=1" in graph
    assert "amix=inputs=3" in graph


def test_filter_graph_includes_both_chimes() -> None:
    graph = _build_filter_complex(
        PROFILE,
        fade_out_start_s=10.0,
        intro_chime_input_index=2,
        outro_chime_input_index=3,
        outro_chime_delay_ms=45000,
    )
    assert "introchime" in graph
    assert "outrochime" in graph
    assert "amix=inputs=4" in graph


def test_mix_background_with_chime_bytes_adds_ffmpeg_inputs(monkeypatch) -> None:
    monkeypatch.setattr(mix_module, "resolve_ffmpeg_executable", lambda: "ffmpeg")
    monkeypatch.setattr(mix_module, "_resolve_ffprobe_executable", lambda _ff: None)
    monkeypatch.setattr(
        mix_module,
        "_resolve_narration_duration_seconds",
        lambda **_kwargs: 12.5,
    )

    captured: list[list[str]] = []

    def fake_run(command, **kwargs):
        captured.append(list(command))
        Path(command[-1]).write_bytes(b"master-mp3-bytes")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(mix_module.subprocess, "run", fake_run)

    out = mix_background(
        b"narration",
        b"bed",
        PROFILE,
        intro_chime_bytes=b"intro-chime-bytes",
        outro_chime_bytes=b"outro-chime-bytes",
    )
    assert out == b"master-mp3-bytes"
    command = captured[0]
    assert command.count("-i") == 4  # narration, bed, intro chime, outro chime
    filter_index = command.index("-filter_complex")
    filter_complex = command[filter_index + 1]
    assert "introchime" in filter_complex
    assert "outrochime" in filter_complex


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_mix_background_real_ffmpeg_with_chimes(tmp_path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    narration = tmp_path / "narration.mp3"
    bed = tmp_path / "bed.mp3"
    chime = tmp_path / "chime.mp3"
    for path, freq, duration in ((narration, 220, 2), (bed, 440, 1), (chime, 880, 1)):
        subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", f"sine=frequency={freq}:duration={duration}", str(path)],
            check=True,
        )

    out = mix_background(
        narration.read_bytes(),
        bed.read_bytes(),
        PROFILE,
        intro_chime_bytes=chime.read_bytes(),
        outro_chime_bytes=chime.read_bytes(),
    )
    assert len(out) > 0
    assert out[:2] == b"\xff\xfb" or out[:3] == b"ID3"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_mix_background_real_ffmpeg(tmp_path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    narration = tmp_path / "narration.mp3"
    bed = tmp_path / "bed.mp3"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "sine=frequency=220:duration=2", str(narration)],
        check=True,
    )
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=1", str(bed)],
        check=True,
    )

    out = mix_background(narration.read_bytes(), bed.read_bytes(), PROFILE)
    assert len(out) > 0
    assert out[:2] == b"\xff\xfb" or out[:3] == b"ID3"

    non_duck = mix_background(
        narration.read_bytes(), bed.read_bytes(), dataclasses.replace(PROFILE, duck=False)
    )
    assert len(non_duck) > 0
