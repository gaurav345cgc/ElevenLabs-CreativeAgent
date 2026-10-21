"""S3 object key layout for TTS audio artifacts.

Layout (per guide/architecture-and-tts-plane.md §14):

  {tenant_id}/{transcript_id}/{audio_job_id}/chunks/{chunk_index}.mp3
  {tenant_id}/{transcript_id}/{audio_job_id}/final/final.mp3
  {tenant_id}/{transcript_id}/{audio_job_id}/final/master.mp3
  {tenant_id}/{transcript_id}/{audio_job_id}/manifest/audio_manifest.json
  {tenant_id}/{transcript_id}/{audio_job_id}/debug/request-{chunk_index}.json
  background/{profile_code}.mp3
"""

from __future__ import annotations

from uuid import UUID


def _segment(value: UUID | str) -> str:
    return str(value)


def job_prefix(tenant_id: UUID | str, transcript_id: UUID | str, audio_job_id: UUID | str) -> str:
    """Prefix for all objects belonging to one audio job."""
    return f"{_segment(tenant_id)}/{_segment(transcript_id)}/{_segment(audio_job_id)}/"


def chunk_object_key(
    tenant_id: UUID | str,
    transcript_id: UUID | str,
    audio_job_id: UUID | str,
    chunk_index: int,
) -> str:
    return f"{job_prefix(tenant_id, transcript_id, audio_job_id)}chunks/{chunk_index}.mp3"


def final_object_key(
    tenant_id: UUID | str,
    transcript_id: UUID | str,
    audio_job_id: UUID | str,
) -> str:
    return f"{job_prefix(tenant_id, transcript_id, audio_job_id)}final/final.mp3"


def master_object_key(
    tenant_id: UUID | str,
    transcript_id: UUID | str,
    audio_job_id: UUID | str,
) -> str:
    return f"{job_prefix(tenant_id, transcript_id, audio_job_id)}final/master.mp3"


def background_track_key(profile_code: str) -> str:
    return f"background/{profile_code}.mp3"


def chime_key(name: str) -> str:
    return f"chimes/{name}.mp3"


def manifest_object_key(
    tenant_id: UUID | str,
    transcript_id: UUID | str,
    audio_job_id: UUID | str,
) -> str:
    return f"{job_prefix(tenant_id, transcript_id, audio_job_id)}manifest/audio_manifest.json"


def debug_request_object_key(
    tenant_id: UUID | str,
    transcript_id: UUID | str,
    audio_job_id: UUID | str,
    chunk_index: int,
) -> str:
    return (
        f"{job_prefix(tenant_id, transcript_id, audio_job_id)}debug/request-{chunk_index}.json"
    )


DEBUG_OBJECT_TAG_KEY = "artifact_kind"
DEBUG_OBJECT_TAG_VALUE = "debug"


def debug_object_tags() -> dict[str, str]:
    """S3 object tags for lifecycle expiration of debug artifacts."""
    return {DEBUG_OBJECT_TAG_KEY: DEBUG_OBJECT_TAG_VALUE}
