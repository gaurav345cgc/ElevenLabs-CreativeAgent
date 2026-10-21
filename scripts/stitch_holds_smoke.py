#!/usr/bin/env python3
"""Smoke test: intercalate silence holds into local speech MP3s (Phase 17).

Validates stitch-with-holds without Aurora, S3, or ElevenLabs.
Requires ffmpeg on PATH (or CREATIVE_AGENT_FFMPEG_PATH).

Holds file formats (JSON):
  [{"after_chunk_index": 0, "hold_seconds": 12}, ...]
  or a PausePlan / MappedPausePlan object with a "holds" array
  (mapped plans use after_chunk_index; unmapped beat/paragraph holds are rejected).

Examples:
  python scripts/stitch_holds_smoke.py \\
    --chunks chunk0.mp3 chunk1.mp3 \\
    --holds output/holds.json \\
    --out output/final-holds-smoke.mp3

  # Then audition with bed:
  python scripts/mix_background_smoke.py \\
    --narration output/final-holds-smoke.mp3 \\
    --bed library/calm_ambient_01.mp3 \\
    --out output/master-holds-smoke.mp3
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from transcript_composer.llm_config import ensure_dotenv_loaded
from tts_pipeline.finalizer.stitch import (
    FinalMergeError,
    HoldSpec,
    merge_mp3_chunks_with_holds,
)


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


def _load_holds(path: Path, *, chunk_count: int) -> list[HoldSpec]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        holds_raw = payload.get("holds")
        if holds_raw is None:
            raise ValueError("holds JSON object must contain a 'holds' array")
    elif isinstance(payload, list):
        holds_raw = payload
    else:
        raise ValueError("holds file must be a JSON array or object with 'holds'")

    if not isinstance(holds_raw, list):
        raise ValueError("'holds' must be an array")

    holds: list[HoldSpec] = []
    for index, item in enumerate(holds_raw):
        if not isinstance(item, dict):
            raise ValueError(f"holds[{index}] must be an object")
        if "after_chunk_index" not in item:
            raise ValueError(
                f"holds[{index}] missing after_chunk_index "
                "(map PausePlan to chunks first, or pass a mapped holds list)"
            )
        after = int(item["after_chunk_index"])
        seconds = int(item["hold_seconds"])
        if after < 0 or after >= chunk_count:
            raise ValueError(
                f"holds[{index}] after_chunk_index={after} out of range "
                f"for {chunk_count} speech chunk(s)"
            )
        if seconds < 1:
            raise ValueError(f"holds[{index}] hold_seconds must be >= 1")
        holds.append((after, seconds))
    return holds


def main() -> int:
    ensure_dotenv_loaded()
    parser = argparse.ArgumentParser(
        description="Interleave silence holds into local speech MP3 chunks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            "  python scripts/stitch_holds_smoke.py \\\n"
            "    --chunks c0.mp3 c1.mp3 \\\n"
            "    --holds holds.json \\\n"
            "    --out output/final-holds-smoke.mp3\n\n"
            "Optional bed audition:\n"
            "  python scripts/mix_background_smoke.py \\\n"
            "    --narration output/final-holds-smoke.mp3 \\\n"
            "    --bed library/calm_ambient_01.mp3 \\\n"
            "    --out output/master-holds-smoke.mp3"
        ),
    )
    parser.add_argument(
        "--chunks",
        type=Path,
        nargs="+",
        required=True,
        help="Speech MP3 chunk files in order (chunk 0, 1, ...)",
    )
    parser.add_argument(
        "--holds",
        type=Path,
        required=True,
        help="JSON holds file: [{after_chunk_index, hold_seconds}, ...] or mapped plan",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("output/final-holds-smoke.mp3"),
        help="Output MP3 path (default: output/final-holds-smoke.mp3)",
    )
    args = parser.parse_args()

    for path in args.chunks:
        if not path.is_file():
            print("error               ", f"chunk file not found: {path}")
            return 1
    if not args.holds.is_file():
        print("error               ", f"holds file not found: {args.holds}")
        return 1

    try:
        holds = _load_holds(args.holds, chunk_count=len(args.chunks))
    except (ValueError, json.JSONDecodeError, OSError, TypeError) as exc:
        print("error               ", str(exc))
        return 1

    chunk_bytes = [path.read_bytes() for path in args.chunks]
    try:
        merged = merge_mp3_chunks_with_holds(chunk_bytes, holds)
    except FinalMergeError as exc:
        print("error               ", str(exc))
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(merged)

    total_hold_seconds = sum(seconds for _, seconds in holds)
    duration_s = _probe_duration_seconds(args.out)
    print("chunk_count         ", len(args.chunks))
    print("hold_count          ", len(holds))
    print("total_hold_seconds  ", total_hold_seconds)
    for after, seconds in holds:
        print(f"hold               ", f"after_chunk={after} seconds={seconds}")
    print("output_path         ", args.out.resolve())
    print("byte_size           ", len(merged))
    if duration_s is not None:
        print("duration_seconds    ", round(duration_s, 2))
    else:
        print("duration_seconds    ", "(install ffprobe to probe output duration)")
    print()
    print(
        "Next (optional): python scripts/mix_background_smoke.py "
        f"--narration {args.out} --bed library/calm_ambient_01.mp3 "
        "--out output/master-holds-smoke.mp3"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
