#!/usr/bin/env python3
"""Smoke test: create a TTS audio job from an ENHANCED transcript (Phase 6).

Uses the deployed API to resolve the latest ELEVENLABS_ENHANCED version unless IDs are passed.
Requires CREATIVE_AGENT_DATABASE_URL and migration 002 applied.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx

from db.session import build_session_factory
from tts_pipeline.intake import AudioJobIntakeService, CreateAudioJobRequest
from tts_pipeline.voice_policy import DEFAULT_VOICE_PROFILE_CODE, list_voice_profile_codes
from transcript_composer.llm_config import ensure_dotenv_loaded

DEFAULT_API_BASE = "https://vwhmjhoym3.execute-api.us-east-1.amazonaws.com"
DEFAULT_TENANT = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
DEFAULT_TRANSCRIPT = UUID("4b68b02a-b75e-4620-a6a6-b5e82f5d4d60")


def _api_headers(api_key: str, tenant_id: UUID) -> dict[str, str]:
    return {"X-API-Key": api_key, "X-Tenant-Id": str(tenant_id)}


def fetch_enhanced_version_id(
    *,
    api_base: str,
    api_key: str,
    tenant_id: UUID,
    transcript_id: UUID,
) -> UUID:
    url = f"{api_base.rstrip('/')}/transcripts/{transcript_id}/versions?include_content=false"
    response = httpx.get(url, headers=_api_headers(api_key, tenant_id), timeout=30)
    response.raise_for_status()
    for version in response.json()["versions"]:
        if version["version_kind"] == "ELEVENLABS_ENHANCED":
            return UUID(version["version_id"])
    raise RuntimeError(f"No ELEVENLABS_ENHANCED version for transcript {transcript_id}")


def main() -> int:
    ensure_dotenv_loaded()
    parser = argparse.ArgumentParser(description="Create TTS audio job in Aurora")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--tenant-id", type=UUID, default=DEFAULT_TENANT)
    parser.add_argument("--transcript-id", type=UUID, default=DEFAULT_TRANSCRIPT)
    parser.add_argument("--transcript-version-id", type=UUID, default=None)
    parser.add_argument(
        "--voice-profile",
        default=DEFAULT_VOICE_PROFILE_CODE,
        choices=list_voice_profile_codes(),
    )
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("CREATIVE_AGENT_API_KEY", "").strip()
    if not api_key:
        print("Set CREATIVE_AGENT_API_KEY or pass --api-key", file=sys.stderr)
        return 1

    version_id = args.transcript_version_id or fetch_enhanced_version_id(
        api_base=args.api_base,
        api_key=api_key,
        tenant_id=args.tenant_id,
        transcript_id=args.transcript_id,
    )

    intake = AudioJobIntakeService(build_session_factory())
    result = intake.create_audio_job(
        CreateAudioJobRequest(
            tenant_id=args.tenant_id,
            transcript_id=args.transcript_id,
            transcript_version_id=version_id,
            voice_profile_code=args.voice_profile,
            correlation_id=str(uuid.uuid4()),
        )
    )

    job = result.audio_job
    print("created             ", result.created)
    print("audio_job_id        ", job.id)
    print("transcript_id       ", job.transcript_id)
    print("transcript_version_id", job.transcript_version_id)
    print("voice_profile       ", job.voice_profile_code)
    print("voice_id            ", job.voice_id)
    print("model_id            ", job.model_id)
    print("output_format       ", job.output_format)
    print("seed                ", job.seed)
    print("status              ", job.status.value)
    print("idempotency_key     ", job.idempotency_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
