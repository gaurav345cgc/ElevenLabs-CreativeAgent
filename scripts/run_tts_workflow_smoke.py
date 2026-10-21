#!/usr/bin/env python3
"""Smoke test: run TTS workflow from a chosen state through completion.

Supports pause-planning replay via --start-at PlanPauses / MapPausesToChunks.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from observability.tts import configure_tts_logging
from db.session import build_session_factory
from tts_pipeline.orchestrator import TtsWorkflowEngine, WorkflowInput, WorkflowState
from transcript_composer.llm_config import ensure_dotenv_loaded


def main() -> int:
    ensure_dotenv_loaded()
    parser = argparse.ArgumentParser(
        description="Run TTS workflow for an audio job",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Replay examples:
  # Re-run pause planning (calls OpenAI unless pause_plan already stored):
  python scripts/run_tts_workflow_smoke.py --audio-job-id <uuid> --start-at PlanPauses

  # Re-map existing pause_plan onto chunks without calling OpenAI:
  python scripts/run_tts_workflow_smoke.py --audio-job-id <uuid> --start-at MapPausesToChunks

  # Re-run background mix when FINAL narration already exists:
  python scripts/run_tts_workflow_smoke.py --audio-job-id <uuid> --start-at MixBackground

  # Re-stitch voice-only final.mp3 only (uses mapped_pause_plan holds if present):
  python scripts/run_tts_workflow_smoke.py --audio-job-id <uuid> --start-at FinalizeFinal

Local pause quality checks without full AWS:
  python scripts/plan_pauses_smoke.py --beats-file beats.txt --target-minutes 10 --dry-fixture
  python scripts/stitch_holds_smoke.py --chunks c0.mp3 c1.mp3 --holds holds.json \\
    --out output/final-holds-smoke.mp3
  python scripts/mix_background_smoke.py \\
    --narration output/final-holds-smoke.mp3 \\
    --bed library/calm_ambient_01.mp3 \\
    --out output/master-holds-smoke.mp3

Re-mix procedure:
  1. Confirm a FINAL asset exists for the job (voice-only narration).
  2. Delete or supersede the MASTER asset row in Aurora if you need a fresh mix.
  3. Replay from MixBackground (see above).
""",
    )
    parser.add_argument("--audio-job-id", type=UUID, required=True)
    parser.add_argument(
        "--start-at",
        default=WorkflowState.GENERATE_CHUNKS_SEQUENTIALLY.value,
        choices=[state.value for state in WorkflowState if state is not WorkflowState.SUCCEEDED],
        help=(
            "Resume mid-flow (default: GenerateChunksSequentially for READY jobs). "
            "Use PlanPauses / MapPausesToChunks for pause-plan replay; "
            "MixBackground to replay only the bed mix when FINAL already exists."
        ),
    )
    args = parser.parse_args()
    configure_tts_logging()

    engine = TtsWorkflowEngine(build_session_factory())
    result = engine.run(
        WorkflowInput(
            audio_job_id=args.audio_job_id,
            start_state=WorkflowState(args.start_at),
            correlation_id=str(uuid.uuid4()),
        )
    )

    print("success             ", result.success)
    print("audio_job_id        ", result.audio_job_id)
    print("correlation_id      ", result.correlation_id)
    print("final_state         ", result.final_state.value)
    if result.error:
        print("error               ", result.error)
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
