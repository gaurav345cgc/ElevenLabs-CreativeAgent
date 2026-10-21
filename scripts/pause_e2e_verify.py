#!/usr/bin/env python3
"""Phase 18 helper: verify pause-plan E2E artifacts for an audio job.

Checks automated checklist items (metadata, duration budget). Does **not**
replace manual listening QA — print the listening checklist for the operator.

Examples:
  python scripts/pause_e2e_verify.py --audio-job-id <uuid>
  python scripts/pause_e2e_verify.py --audio-job-id <uuid> --final-mp3 output/final-<uuid>.mp3
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from db.repositories import AudioJobRepository
from db.session import build_session_factory, session_scope
from transcript_composer.llm_config import ensure_dotenv_loaded
from tts_pipeline.finalizer.manifest import pause_plan_summary_from_metadata
from tts_pipeline.pause_planner.service import MAPPED_PAUSE_PLAN_KEY, PAUSE_PLAN_KEY


LISTENING_CHECKLIST = [
    "Short piece (~5–8 min): practice holds feel natural (not choppy)",
    "Medium (~10–12 min): at least one longer section/integration hold",
    "Hold after instruction: enough time to *do* the cue",
    "No spoken “pause” stage directions",
    "Bed continues during holds (not silence of everything)",
    "Closing integration hold ~30–60s when appropriate",
    "Retry same job: identical hold placement (idempotent)",
]


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
    parser = argparse.ArgumentParser(
        description="Verify pause-plan metadata and optional final.mp3 duration for E2E QA",
    )
    parser.add_argument("--audio-job-id", type=UUID, required=True)
    parser.add_argument(
        "--final-mp3",
        type=Path,
        default=None,
        help="Optional local final.mp3 to compare duration vs speech + holds",
    )
    parser.add_argument(
        "--master-mp3",
        type=Path,
        default=None,
        help="Optional local master.mp3 (presence check only; listening required)",
    )
    parser.add_argument(
        "--tolerance-seconds",
        type=float,
        default=2.5,
        help="Allowed |final_duration - (speech_est + holds)| slack (default 2.5s)",
    )
    args = parser.parse_args()

    repo = AudioJobRepository(build_session_factory())
    with session_scope(repo._session_factory) as session:
        job = repo.get_audio_job(session, args.audio_job_id)
        if job is None:
            print("error               ", f"audio job {args.audio_job_id} not found")
            return 1
        chunks = repo.list_audio_chunks(session, args.audio_job_id)
        final_asset = repo.find_final_asset(session, args.audio_job_id)
        master_asset = repo.find_master_asset(session, args.audio_job_id)
        metadata = dict(job.metadata_json or {})

    has_plan = isinstance(metadata.get(PAUSE_PLAN_KEY), dict)
    has_mapped = isinstance(metadata.get(MAPPED_PAUSE_PLAN_KEY), dict)
    summary = pause_plan_summary_from_metadata(metadata)

    print("audio_job_id        ", job.id)
    print("status              ", job.status.value if hasattr(job.status, "value") else job.status)
    print("has_pause_plan      ", has_plan)
    print("has_mapped_plan     ", has_mapped)
    if summary:
        print("hold_count          ", summary["hold_count"])
        print("total_hold_seconds  ", summary["total_hold_seconds"])
        print("policy_version      ", summary.get("policy_version"))
        print("prompt_version      ", summary.get("prompt_version"))
    else:
        print("pause_summary       ", None)

    speech_ms = sum((chunk.actual_duration_ms or chunk.estimated_duration_ms or 0) for chunk in chunks)
    speech_seconds = speech_ms / 1000.0 if speech_ms else None
    if speech_seconds is not None:
        print("speech_est_seconds  ", round(speech_seconds, 2))

    print("final_asset         ", str(final_asset.id) if final_asset else None)
    print("master_asset        ", str(master_asset.id) if master_asset else None)

    checks: list[tuple[str, bool, str]] = [
        ("pause_plan present", has_plan, "job.metadata_json.pause_plan"),
        ("mapped_pause_plan present", has_mapped, "job.metadata_json.mapped_pause_plan"),
        ("final asset registered", final_asset is not None, "FINAL asset row"),
        ("master asset registered", master_asset is not None, "MASTER asset row (bed mix)"),
    ]

    if args.final_mp3 is not None:
        if not args.final_mp3.is_file():
            print("error               ", f"final mp3 not found: {args.final_mp3}")
            return 1
        duration = _probe_duration_seconds(args.final_mp3)
        print("final_mp3           ", args.final_mp3.resolve())
        print("final_duration_s    ", round(duration, 2) if duration is not None else "(no ffprobe)")
        if duration is not None and summary is not None and speech_seconds is not None:
            expected = speech_seconds + float(summary["total_hold_seconds"])
            delta = abs(duration - expected)
            ok = delta <= args.tolerance_seconds
            checks.append(
                (
                    "final duration ≈ speech + holds",
                    ok,
                    f"got={duration:.2f}s expected≈{expected:.2f}s Δ={delta:.2f}s",
                )
            )
        elif duration is None:
            checks.append(("final duration probe", False, "ffprobe unavailable"))

    if args.master_mp3 is not None:
        ok = args.master_mp3.is_file()
        checks.append(("master mp3 present locally", ok, str(args.master_mp3)))
        if ok:
            master_dur = _probe_duration_seconds(args.master_mp3)
            if master_dur is not None:
                print("master_duration_s   ", round(master_dur, 2))

    print()
    print("=== Automated checks ===")
    failed = 0
    for label, ok, detail in checks:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{mark}] {label} — {detail}")

    if not has_plan:
        print()
        print(
            "NOTE: missing pause_plan usually means the deployed TTS worker predates "
            "pause planning. Rebuild/deploy Lambda (Phase 19) before re-running E2E."
        )

    print()
    print("=== Manual listening QA (operator sign-off required) ===")
    for item in LISTENING_CHECKLIST:
        print(f"[ ] {item}")
    print()
    print(
        "Exit criteria: Slice 5 E2E signed off by listening, not only this script."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
