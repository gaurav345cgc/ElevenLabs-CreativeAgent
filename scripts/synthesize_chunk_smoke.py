#!/usr/bin/env python3
"""Smoke test: synthesize one TTS chunk and write to S3 (Phase 4).

Uses your latest ENHANCED transcript from the API unless IDs are passed explicitly.
Requires CREATIVE_AGENT_ELEVENLABS_API_KEY and CREATIVE_AGENT_TTS_AUDIO_BUCKET in .env.
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

import httpx

from tts_pipeline.generator import ElevenLabsClient, synthesize_and_store_chunk
from tts_pipeline.generator.config import require_elevenlabs_api_key, resolve_tts_audio_bucket
from tts_pipeline.voice_policy import (
    DEFAULT_VOICE_PROFILE_CODE,
    build_speech_synthesis_request,
    get_voice_profile,
    list_voice_profile_codes,
)
from transcript_composer.llm_config import ensure_dotenv_loaded

DEFAULT_API_BASE = "https://vwhmjhoym3.execute-api.us-east-1.amazonaws.com"
DEFAULT_TENANT = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
DEFAULT_TRANSCRIPT = UUID("4b68b02a-b75e-4620-a6a6-b5e82f5d4d60")


def _api_headers(api_key: str, tenant_id: UUID) -> dict[str, str]:
    return {"X-API-Key": api_key, "X-Tenant-Id": str(tenant_id)}


def fetch_first_enhanced_paragraph(
    *,
    api_base: str,
    api_key: str,
    tenant_id: UUID,
    transcript_id: UUID,
) -> tuple[UUID, str]:
    url = f"{api_base.rstrip('/')}/transcripts/{transcript_id}/versions?include_content=true"
    response = httpx.get(url, headers=_api_headers(api_key, tenant_id), timeout=30)
    response.raise_for_status()
    for version in response.json()["versions"]:
        if version["version_kind"] == "ELEVENLABS_ENHANCED":
            version_id = UUID(version["version_id"])
            first = version["content_text"].split("\n\n")[0].strip()
            return version_id, first
    raise RuntimeError(f"No ELEVENLABS_ENHANCED version for transcript {transcript_id}")


def main() -> int:
    ensure_dotenv_loaded()
    parser = argparse.ArgumentParser(description="Synthesize one chunk to S3")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--api-key", default=None, help="Intake API key (default: CREATIVE_AGENT_API_KEY)")
    parser.add_argument("--tenant-id", type=UUID, default=DEFAULT_TENANT)
    parser.add_argument("--transcript-id", type=UUID, default=DEFAULT_TRANSCRIPT)
    parser.add_argument("--audio-job-id", type=UUID, default=None, help="Smoke-test job id (default: new UUID)")
    parser.add_argument(
        "--voice-profile",
        default=DEFAULT_VOICE_PROFILE_CODE,
        choices=list_voice_profile_codes(),
        help="Approved voice profile (Phase 5 policy)",
    )
    parser.add_argument("--list-voice-profiles", action="store_true", help="List profiles and exit")
    parser.add_argument("--chunk-index", type=int, default=0)
    args = parser.parse_args()

    if args.list_voice_profiles:
        for code in list_voice_profile_codes():
            profile = get_voice_profile(code)
            print(f"{code:28} {profile.display_name}  voice_id={profile.voice_id}")
        return 0

    import os

    api_key = args.api_key or os.environ.get("CREATIVE_AGENT_API_KEY", "").strip()
    if not api_key:
        print("Set CREATIVE_AGENT_API_KEY or pass --api-key", file=sys.stderr)
        return 1

    require_elevenlabs_api_key()
    bucket = resolve_tts_audio_bucket()
    if not bucket:
        print("Set CREATIVE_AGENT_TTS_AUDIO_BUCKET", file=sys.stderr)
        return 1

    enhanced_version_id, chunk_text = fetch_first_enhanced_paragraph(
        api_base=args.api_base,
        api_key=api_key,
        tenant_id=args.tenant_id,
        transcript_id=args.transcript_id,
    )
    audio_job_id = args.audio_job_id or uuid.uuid4()

    profile = get_voice_profile(args.voice_profile)
    request = build_speech_synthesis_request(args.voice_profile, chunk_text)

    client = ElevenLabsClient.from_env()
    stored = synthesize_and_store_chunk(
        client,
        request,
        tenant_id=args.tenant_id,
        transcript_id=args.transcript_id,
        audio_job_id=audio_job_id,
        chunk_index=args.chunk_index,
    )

    print("tenant_id           ", args.tenant_id)
    print("transcript_id       ", args.transcript_id)
    print("enhanced_version_id ", enhanced_version_id)
    print("audio_job_id        ", audio_job_id)
    print("chunk_index         ", args.chunk_index)
    print("voice_profile       ", args.voice_profile)
    print("voice_id            ", profile.voice_id)
    print("model_id            ", profile.default_model_id)
    print("seed                ", request.seed)
    print("chunk_text          ", chunk_text)
    print("request_id          ", stored.result.request_id)
    print("byte_size           ", stored.result.byte_size)
    print("checksum_sha256     ", stored.result.checksum_sha256)
    print("s3://{}/{}".format(stored.stored.bucket, stored.stored.object_key))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
