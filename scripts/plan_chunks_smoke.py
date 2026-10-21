#!/usr/bin/env python3
"""Smoke test: plan and persist TTS chunks for an audio job (Phase 7)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from db.session import build_session_factory
from tts_pipeline.chunk_planner import ChunkPlanningService
from transcript_composer.llm_config import ensure_dotenv_loaded


def main() -> int:
    ensure_dotenv_loaded()
    parser = argparse.ArgumentParser(description="Plan and persist TTS chunks for an audio job")
    parser.add_argument("--audio-job-id", type=UUID, required=True)
    args = parser.parse_args()

    planner = ChunkPlanningService(build_session_factory())
    result = planner.plan_and_persist(args.audio_job_id)

    print("created             ", result.created)
    print("audio_job_id        ", result.audio_job_id)
    print("boundary_source     ", result.boundary_source.value)
    print("chunk_count         ", len(result.chunks))
    for chunk in result.chunks:
        preview = chunk.source_text.replace("\n", " ")[:72]
        print(
            f"  [{chunk.chunk_index}] chars={chunk.character_count} "
            f"dur_ms={chunk.estimated_duration_ms} text={preview!r}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
