#!/usr/bin/env python3
"""Smoke test: stitch FINAL, mix MASTER, and persist manifest for a TTS job."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from db.repositories import AudioJobRepository
from db.session import build_session_factory, session_scope
from tts_pipeline.finalizer import (
    finalize_audio_job_final,
    finalize_audio_job_manifest,
    finalize_audio_job_master,
)
from transcript_composer.llm_config import ensure_dotenv_loaded


def main() -> int:
    ensure_dotenv_loaded()
    parser = argparse.ArgumentParser(description="Finalize TTS manifest for an audio job")
    parser.add_argument("--audio-job-id", type=UUID, required=True)
    args = parser.parse_args()

    session_factory = build_session_factory()
    repo = AudioJobRepository(session_factory)

    with session_scope(session_factory) as session:
        job = repo.get_audio_job(session, args.audio_job_id)
        if job is None:
            print("error               ", f"audio job {args.audio_job_id} not found")
            return 1
        chunks = repo.list_audio_chunks(session, args.audio_job_id)
        final_result = finalize_audio_job_final(session, repo, job, chunks)
        master_result = finalize_audio_job_master(session, repo, job)
        result = finalize_audio_job_manifest(
            session,
            repo,
            job,
            chunks,
            final_asset=final_result.asset,
            master_asset=master_result.asset,
        )
        job = repo.get_audio_job(session, args.audio_job_id)

    print("audio_job_id        ", args.audio_job_id)
    print("final_skipped       ", final_result.skipped)
    print("final_asset_id      ", final_result.asset.id)
    print("final_object_key    ", final_result.asset.object_key)
    print("final_byte_size     ", final_result.byte_size)
    print("master_skipped      ", master_result.skipped)
    print("master_asset_id     ", master_result.asset.id)
    print("master_object_key   ", master_result.asset.object_key)
    print("master_byte_size    ", master_result.byte_size)
    print("manifest_skipped    ", result.skipped)
    print("manifest_asset_id   ", result.asset.id)
    print("manifest_object_key ", result.asset.object_key)
    print("chunk_count         ", result.manifest.chunk_count)
    print("total_duration_ms   ", result.manifest.total_duration_ms)
    print("checksum_sha256     ", result.manifest.checksum_sha256)
    if result.stored:
        print("s3_bucket           ", result.stored.bucket)
    if job and job.final_asset_id:
        print("job.final_asset_id  ", job.final_asset_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
