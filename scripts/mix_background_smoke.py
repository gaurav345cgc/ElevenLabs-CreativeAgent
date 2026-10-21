#!/usr/bin/env python3
"""Smoke test: mix local narration MP3 with a background bed (Phase 17).

Validates ffmpeg mix quality without Aurora, S3, or the full TTS workflow.
Requires ffmpeg on PATH (or CREATIVE_AGENT_FFMPEG_PATH).

Example:
  python scripts/mix_background_smoke.py \\
    --narration output/final-<uuid>.mp3 \\
    --bed library/calm_ambient_01.mp3 \\
    --out output/master-smoke.mp3
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tts_pipeline.background_policy import (
    get_background_profile,
    list_background_profile_codes,
    resolve_background_profile,
)
from tts_pipeline.finalizer.mix import BackgroundMixError, mix_background
from transcript_composer.llm_config import ensure_dotenv_loaded


def _probe_duration_seconds(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
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
        str(path),
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


def main() -> int:
    ensure_dotenv_loaded()
    approved = list_background_profile_codes()
    parser = argparse.ArgumentParser(
        description="Mix local narration MP3 with a background bed using approved profile settings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Use this script to audition ducking, bed level, and tail padding before "
            "running the full TTS workflow.\n\n"
            "Example:\n"
            "  python scripts/mix_background_smoke.py \\\n"
            "    --narration output/final-<uuid>.mp3 \\\n"
            "    --bed library/calm_ambient_01.mp3 \\\n"
            "    --out output/master-smoke.mp3"
        ),
    )
    parser.add_argument("--narration", type=Path, required=True, help="Voice-only final narration MP3")
    parser.add_argument("--bed", type=Path, required=True, help="Local background bed MP3")
    parser.add_argument("--out", type=Path, required=True, help="Output master MP3 path")
    parser.add_argument(
        "--profile-code",
        choices=approved or None,
        default=None,
        help="Approved mix profile (default: policy resolver default)",
    )
    args = parser.parse_args()

    if not args.narration.is_file():
        print("error               ", f"narration file not found: {args.narration}")
        return 1
    if not args.bed.is_file():
        print("error               ", f"bed file not found: {args.bed}")
        return 1

    profile = (
        get_background_profile(args.profile_code)
        if args.profile_code
        else resolve_background_profile()
    )
    narration_bytes = args.narration.read_bytes()
    bed_bytes = args.bed.read_bytes()

    try:
        master_bytes = mix_background(narration_bytes, bed_bytes, profile)
    except BackgroundMixError as exc:
        print("error               ", str(exc))
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(master_bytes)

    duration_s = _probe_duration_seconds(args.out)
    print("profile_code        ", profile.code)
    print("profile_display     ", profile.display_name)
    print("narration_path      ", args.narration.resolve())
    print("bed_path            ", args.bed.resolve())
    print("output_path         ", args.out.resolve())
    print("byte_size           ", len(master_bytes))
    if duration_s is not None:
        print("duration_seconds    ", round(duration_s, 2))
    else:
        print("duration_seconds    ", "(install ffprobe to probe output duration)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
