#!/usr/bin/env python3
"""Build concrete catalog notes for background beds.

Combines:
1) Objective ffmpeg/ffprobe metrics (duration, loudness)
2) Strict gpt-audio-mini listening (no marketing priming)

Writes: tts_pipeline/data/background_bed_listen_notes.json
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dotenv import load_dotenv

from tts_pipeline.background_policy.library_catalog import LIBRARY_BED_UPLOADS
from tts_pipeline.background_policy.profiles import display_name_for_code

OUT_PATH = REPO / "tts_pipeline" / "data" / "background_bed_listen_notes.json"
LIBRARY = REPO / "library"
CLIP_SECONDS = 25
CLIP_START = 20  # skip intros; sample the body of the loop
MODEL = "gpt-audio-mini"

STRICT_PROMPT = """You are an audio cataloguer. LISTEN ONLY to this non-vocal bed.

Hard rules:
- Describe only what is audibly present.
- Do NOT invent vocals, lyrics, nature FX, or instruments you cannot hear.
- Do NOT mention 432 Hz, healing frequencies, chakras, or marketing claims.
- Do NOT say "excellent for meditation" fluff.
- If unsure, lower confidence and say so.

Return JSON only:
{
  "audible_layers": ["concrete layer 1", "concrete layer 2"],
  "pulse_or_rhythm": "none|very_subtle|clear",
  "brightness": "dark|neutral|bright",
  "stereo_motion": "still|slow_movement|noticeable_movement",
  "low_end": "thin|moderate|heavy",
  "would_distract_under_voice": "no|maybe|yes",
  "concrete_fingerprint": "one specific audible trait that distinguishes this clip",
  "best_fit_scripts": "short practical use based on sound only",
  "avoid_scripts": "when this bed would fight a voice",
  "one_line": "one concrete sentence with audible traits only",
  "confidence_0_to_5": 0
}
"""


def _ffmpeg() -> str:
    return os.environ.get("CREATIVE_AGENT_FFMPEG_PATH", "ffmpeg")


def _ffprobe() -> str:
    return os.environ.get("CREATIVE_AGENT_FFPROBE_PATH", "ffprobe")


def measure_bed(src: Path) -> dict:
    probe = subprocess.run(
        [
            _ffprobe(),
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(src),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    meta = json.loads(probe.stdout)
    stream = next(s for s in meta["streams"] if s.get("codec_type") == "audio")
    duration_s = float(meta["format"].get("duration") or stream.get("duration") or 0)

    volume = subprocess.run(
        [
            _ffmpeg(),
            "-hide_banner",
            "-i",
            str(src),
            "-t",
            "90",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    mean_v = max_v = None
    for line in volume.stderr.splitlines():
        if "mean_volume:" in line:
            mean_v = float(line.split("mean_volume:")[1].split("dB")[0].strip())
        if "max_volume:" in line:
            max_v = float(line.split("max_volume:")[1].split("dB")[0].strip())

    return {
        "duration_s": round(duration_s, 1),
        "sample_rate": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
        "mean_volume_db": mean_v,
        "max_volume_db": max_v,
    }


def make_clip(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _ffmpeg(),
        "-y",
        "-ss",
        str(CLIP_START),
        "-i",
        str(src),
        "-t",
        str(CLIP_SECONDS),
        "-ac",
        "1",
        "-ar",
        "24000",
        "-b:a",
        "96k",
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def listen_bed(client, clip: Path, *, code: str, filename: str) -> dict:
    b64 = base64.b64encode(clip.read_bytes()).decode()
    user = (
        f"Bed code: {code}\n"
        f"Filename: {filename}\n"
        f"Display name: {display_name_for_code(code)}\n\n"
        f"{STRICT_PROMPT}"
    )
    response = client.chat.completions.create(
        model=MODEL,
        modalities=["text"],
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user},
                    {"type": "input_audio", "input_audio": {"data": b64, "format": "mp3"}},
                ],
            }
        ],
        temperature=0.1,
    )
    content = (response.choices[0].message.content or "").strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:].strip()
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("listener returned non-object JSON")
    return payload


def loudness_rank_label(mean_db: float | None, all_means: list[float]) -> str | None:
    if mean_db is None or not all_means:
        return None
    ordered = sorted(all_means)
    # quieter = more negative dB
    idx = ordered.index(mean_db) if mean_db in ordered else None
    if idx is None:
        # nearest
        idx = min(range(len(ordered)), key=lambda i: abs(ordered[i] - mean_db))
    n = len(ordered)
    if idx <= max(0, n // 3 - 1):
        return "among quieter third of catalog"
    if idx >= n - max(1, n // 3):
        return "among louder third of catalog"
    return "mid loudness vs catalog"


def build_concrete_summary(notes: dict) -> str:
    obj = notes.get("objective") or {}
    listen = notes.get("listen") or {}
    parts: list[str] = []
    one = str(listen.get("one_line") or "").strip()
    if one:
        parts.append(one)
    bits: list[str] = []
    if obj.get("mean_volume_db") is not None:
        bits.append(f"mean_loudness={obj['mean_volume_db']}dB")
    if obj.get("loudness_vs_catalog"):
        bits.append(obj["loudness_vs_catalog"])
    if obj.get("duration_s") is not None:
        bits.append(f"loop≈{obj['duration_s']}s")
    for key in ("brightness", "low_end", "pulse_or_rhythm", "stereo_motion"):
        val = listen.get(key)
        if val:
            bits.append(f"{key}={val}")
    if listen.get("concrete_fingerprint"):
        bits.append(f"fingerprint={listen['concrete_fingerprint']}")
    if listen.get("would_distract_under_voice"):
        bits.append(f"under_voice_risk={listen['would_distract_under_voice']}")
    if listen.get("confidence_0_to_5") is not None:
        bits.append(f"listen_confidence={listen['confidence_0_to_5']}/5")
    if bits:
        parts.append("(" + "; ".join(bits) + ")")
    return " ".join(parts)


def main() -> int:
    load_dotenv(REPO / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", help="Limit to these profile codes")
    parser.add_argument("--skip-listen", action="store_true", help="Metrics only")
    args = parser.parse_args()

    from openai import OpenAI
    from transcript_composer.llm_config import require_openai_api_key

    client = None if args.skip_listen else OpenAI(api_key=require_openai_api_key())
    only = set(args.only or [])

    # Pass 1: objective metrics for whole catalog (needed for relative loudness)
    objectives: dict[str, dict] = {}
    for filename, code in sorted(LIBRARY_BED_UPLOADS.items(), key=lambda x: x[1]):
        if only and code not in only:
            continue
        src = LIBRARY / filename
        if not src.exists():
            print(f"missing {filename}")
            continue
        print(f"measure {code}")
        objectives[code] = {"source_filename": filename, **measure_bed(src)}

    means = [
        v["mean_volume_db"]
        for v in objectives.values()
        if isinstance(v.get("mean_volume_db"), (int, float))
    ]
    for code, obj in objectives.items():
        obj["loudness_vs_catalog"] = loudness_rank_label(obj.get("mean_volume_db"), means)

    beds: dict[str, dict] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="bg_listen_") as tmp:
        tmp_path = Path(tmp)
        for code, obj in objectives.items():
            filename = obj["source_filename"]
            src = LIBRARY / filename
            entry: dict = {
                "code": code,
                "display_name": display_name_for_code(code),
                "source_filename": filename,
                "objective": {
                    k: v
                    for k, v in obj.items()
                    if k != "source_filename"
                },
                "listener_model": None if args.skip_listen else MODEL,
                "clip_seconds": CLIP_SECONDS,
                "clip_start_seconds": CLIP_START,
            }
            if not args.skip_listen:
                assert client is not None
                clip = tmp_path / f"{code}.mp3"
                print(f"listen {code}")
                try:
                    make_clip(src, clip)
                    listen = listen_bed(client, clip, code=code, filename=filename)
                    # strip banned marketing if model slips
                    blob = json.dumps(listen).lower()
                    if "432" in blob:
                        listen["warning"] = "model mentioned 432; treat that claim as unreliable"
                    entry["listen"] = listen
                    print(f"  -> {listen.get('one_line', '')[:120]}")
                except Exception as exc:
                    print(f"  FAIL {code}: {exc}")
                    failures.append(code)
                    entry["listen"] = {"error": str(exc), "confidence_0_to_5": 0}
            entry["one_line"] = (entry.get("listen") or {}).get("one_line") or ""
            entry["concrete_summary"] = build_concrete_summary(entry)
            # selector-facing aliases
            entry["best_for"] = (entry.get("listen") or {}).get("best_fit_scripts")
            entry["avoid_when"] = (entry.get("listen") or {}).get("avoid_scripts")
            entry["distinctive"] = (entry.get("listen") or {}).get("concrete_fingerprint")
            beds[code] = entry

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "2.0",
        "method": "objective_ffmpeg_volumedetect + strict gpt-audio-mini listen",
        "listener_model": None if args.skip_listen else MODEL,
        "clip_seconds": CLIP_SECONDS,
        "clip_start_seconds": CLIP_START,
        "catalog_mean_volume_db": round(statistics.mean(means), 2) if means else None,
        "beds": beds,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH} ({len(beds)} beds)")
    if failures:
        print(f"failures: {', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
