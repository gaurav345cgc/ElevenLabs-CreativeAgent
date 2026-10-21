"""Audio job manifest schema and assembly."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from models.enums import AudioChunkStatus, AudioJobStatus
from models.records import TranscriptAudioChunkRecord, TranscriptAudioJobRecord
from tts_pipeline.pause_planner.service import (
    MAPPED_PAUSE_PLAN_KEY,
    PAUSE_PLAN_KEY,
    PAUSE_PLAN_VERSIONS_KEY,
)

MANIFEST_SCHEMA_VERSION = "tts-audio-manifest-v1"


@dataclass(frozen=True, slots=True)
class ManifestChunkEntry:
    chunk_index: int
    chunk_id: str
    status: str
    request_id: str | None
    object_key: str
    byte_size: int | None
    checksum_sha256: str | None
    duration_ms: int | None
    character_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_index": self.chunk_index,
            "chunk_id": self.chunk_id,
            "status": self.status,
            "request_id": self.request_id,
            "object_key": self.object_key,
            "byte_size": self.byte_size,
            "checksum_sha256": self.checksum_sha256,
            "duration_ms": self.duration_ms,
            "character_count": self.character_count,
        }


@dataclass(frozen=True, slots=True)
class AudioJobManifest:
    schema_version: str
    transcript_id: str
    transcript_version_id: str
    audio_job_id: str
    tenant_id: str
    voice_profile_code: str | None
    voice_id: str
    model_id: str
    output_format: str
    status: str
    chunk_count: int
    total_duration_ms: int | None
    chunks: tuple[ManifestChunkEntry, ...]
    generated_at: str
    correlation_id: str | None = None
    final_object_key: str | None = None
    final_asset_id: str | None = None
    final_checksum_sha256: str | None = None
    final_byte_size: int | None = None
    master_object_key: str | None = None
    master_asset_id: str | None = None
    master_checksum_sha256: str | None = None
    master_byte_size: int | None = None
    background_profile_code: str | None = None
    background_track_key: str | None = None
    pause_plan_summary: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "transcript_id": self.transcript_id,
            "transcript_version_id": self.transcript_version_id,
            "audio_job_id": self.audio_job_id,
            "tenant_id": self.tenant_id,
            "voice_profile_code": self.voice_profile_code,
            "voice_id": self.voice_id,
            "model_id": self.model_id,
            "output_format": self.output_format,
            "status": self.status,
            "chunk_count": self.chunk_count,
            "total_duration_ms": self.total_duration_ms,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
            "generated_at": self.generated_at,
            "correlation_id": self.correlation_id,
        }
        if self.final_object_key is not None:
            payload["final_object_key"] = self.final_object_key
        if self.final_asset_id is not None:
            payload["final_asset_id"] = self.final_asset_id
        if self.final_checksum_sha256 is not None:
            payload["final_checksum_sha256"] = self.final_checksum_sha256
        if self.final_byte_size is not None:
            payload["final_byte_size"] = self.final_byte_size
        if self.master_object_key is not None:
            payload["master_object_key"] = self.master_object_key
        if self.master_asset_id is not None:
            payload["master_asset_id"] = self.master_asset_id
        if self.master_checksum_sha256 is not None:
            payload["master_checksum_sha256"] = self.master_checksum_sha256
        if self.master_byte_size is not None:
            payload["master_byte_size"] = self.master_byte_size
        if self.background_profile_code is not None:
            payload["background_profile_code"] = self.background_profile_code
        if self.background_track_key is not None:
            payload["background_track_key"] = self.background_track_key
        if self.pause_plan_summary is not None:
            payload["pause_plan_summary"] = self.pause_plan_summary
        return payload

    def to_json_bytes(self) -> bytes:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True).encode("utf-8")

    @property
    def checksum_sha256(self) -> str:
        return hashlib.sha256(self.to_json_bytes()).hexdigest()


def chunk_duration_ms(chunk: TranscriptAudioChunkRecord) -> int | None:
    if chunk.actual_duration_ms is not None:
        return chunk.actual_duration_ms
    return chunk.estimated_duration_ms


def pause_plan_summary_from_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """Operator-facing pause summary — no full hold dump.

    Prefers mapped plan totals when present (what stitch used); versions come from
    the normalized ``pause_plan`` / ``pause_plan_versions``.
    """
    if not isinstance(metadata, dict):
        return None

    plan = metadata.get(PAUSE_PLAN_KEY)
    mapped = metadata.get(MAPPED_PAUSE_PLAN_KEY)
    versions = metadata.get(PAUSE_PLAN_VERSIONS_KEY)
    if not isinstance(versions, dict):
        versions = {}

    source = mapped if isinstance(mapped, dict) else plan if isinstance(plan, dict) else None
    if source is None:
        return None

    holds = source.get("holds")
    if not isinstance(holds, list):
        holds = []
    total = source.get("total_hold_seconds")
    if total is None:
        total = sum(int(item.get("hold_seconds", 0)) for item in holds if isinstance(item, dict))

    policy_version = None
    prompt_version = None
    if isinstance(plan, dict):
        policy_version = plan.get("policy_version")
        prompt_version = plan.get("prompt_version")
    policy_version = policy_version or versions.get("policy_version")
    prompt_version = prompt_version or versions.get("prompt_version")

    return {
        "hold_count": len(holds),
        "total_hold_seconds": int(total or 0),
        "policy_version": policy_version,
        "prompt_version": prompt_version,
    }


def build_audio_job_manifest(
    job: TranscriptAudioJobRecord,
    chunks: list[TranscriptAudioChunkRecord],
    *,
    correlation_id: str | None = None,
    generated_at: datetime | None = None,
    final_object_key: str | None = None,
    final_asset_id: str | None = None,
    final_checksum_sha256: str | None = None,
    final_byte_size: int | None = None,
    master_object_key: str | None = None,
    master_asset_id: str | None = None,
    master_checksum_sha256: str | None = None,
    master_byte_size: int | None = None,
    background_profile_code: str | None = None,
    background_track_key: str | None = None,
    pause_plan_summary: dict[str, Any] | None = None,
) -> AudioJobManifest:
    """Build manifest JSON payload from completed chunk rows."""
    completed = [
        chunk
        for chunk in sorted(chunks, key=lambda item: item.chunk_index)
        if chunk.status is AudioChunkStatus.COMPLETED and chunk.output_object_key
    ]
    if not completed:
        raise ValueError(f"audio job {job.id} has no completed chunks for manifest")

    entries: list[ManifestChunkEntry] = []
    total_duration_ms = 0
    has_duration = False

    for chunk in completed:
        metadata = chunk.metadata_json or {}
        duration_ms = chunk_duration_ms(chunk)
        if duration_ms is not None:
            has_duration = True
            total_duration_ms += duration_ms

        entries.append(
            ManifestChunkEntry(
                chunk_index=chunk.chunk_index,
                chunk_id=str(chunk.id),
                status=chunk.status.value,
                request_id=chunk.eleven_request_id,
                object_key=chunk.output_object_key or "",
                byte_size=metadata.get("byte_size"),
                checksum_sha256=metadata.get("checksum_sha256"),
                duration_ms=duration_ms,
                character_count=chunk.character_count,
            )
        )

    summary = (
        pause_plan_summary
        if pause_plan_summary is not None
        else pause_plan_summary_from_metadata(job.metadata_json)
    )

    timestamp = generated_at or datetime.now(UTC)
    return AudioJobManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        transcript_id=str(job.transcript_id),
        transcript_version_id=str(job.transcript_version_id),
        audio_job_id=str(job.id),
        tenant_id=str(job.tenant_id),
        voice_profile_code=job.voice_profile_code,
        voice_id=job.voice_id,
        model_id=job.model_id,
        output_format=job.output_format,
        status=job.status.value if isinstance(job.status, AudioJobStatus) else str(job.status),
        chunk_count=len(entries),
        total_duration_ms=total_duration_ms if has_duration else None,
        chunks=tuple(entries),
        generated_at=timestamp.isoformat(),
        correlation_id=correlation_id,
        final_object_key=final_object_key,
        final_asset_id=final_asset_id,
        final_checksum_sha256=final_checksum_sha256,
        final_byte_size=final_byte_size,
        master_object_key=master_object_key,
        master_asset_id=master_asset_id,
        master_checksum_sha256=master_checksum_sha256,
        master_byte_size=master_byte_size,
        background_profile_code=background_profile_code,
        background_track_key=background_track_key,
        pause_plan_summary=summary,
    )
