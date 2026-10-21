"""Finalize TTS jobs — manifest JSON in S3 and asset metadata in Aurora."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy.orm import Session

from db.repositories import AudioJobRepository
from db.repositories.types import CreateAudioAssetInput
from models.enums import AudioAssetKind, AudioChunkStatus, AudioJobStatus
from models.records import TranscriptAudioAssetRecord, TranscriptAudioChunkRecord, TranscriptAudioJobRecord
from observability.tts import (
    log_tts_final_merged,
    log_tts_manifest_finalized,
    log_tts_master_mixed,
    log_tts_storage_failure,
)
from tts_pipeline.background_policy import resolve_background_profile
from tts_pipeline.finalizer.manifest import AudioJobManifest, build_audio_job_manifest
from tts_pipeline.finalizer.mix import BackgroundMixError, MixFn, mix_background
from tts_pipeline.finalizer.stitch import (
    FinalMergeError,
    HoldSpec,
    MergeFn,
    merge_mp3_chunks,
    merge_mp3_chunks_with_holds,
)
from tts_pipeline.persistence.s3_audio import StoredAudioObject, read_object_bytes, write_audio_object, write_json_object
from tts_pipeline.persistence.s3_keys import final_object_key, manifest_object_key, master_object_key
from tts_pipeline.pause_planner.schema import MappedPausePlan
from tts_pipeline.pause_planner.service import MAPPED_PAUSE_PLAN_KEY


MANIFEST_FINALIZED_EVENT = "MANIFEST_FINALIZED"
MANIFEST_SKIPPED_EVENT = "MANIFEST_SKIPPED"
FINAL_MERGED_EVENT = "FINAL_MERGED"
FINAL_SKIPPED_EVENT = "FINAL_SKIPPED"
MASTER_MIXED_EVENT = "MASTER_MIXED"
MASTER_SKIPPED_EVENT = "MASTER_SKIPPED"


class ManifestFinalizationError(RuntimeError):
    """Manifest could not be built or persisted."""


class FinalAudioMergeError(RuntimeError):
    """Final narration merge could not be completed."""


def _log_and_reraise_storage_failure(
    exc: Exception,
    *,
    job: TranscriptAudioJobRecord,
    object_key: str,
    correlation_id: str | None,
    artifact_kind: str,
) -> None:
    log_tts_storage_failure(
        audio_job_id=str(job.id),
        transcript_id=str(job.transcript_id),
        object_key=object_key,
        artifact_kind=artifact_kind,
        error_type=type(exc).__name__,
        error_message=str(exc)[:500],
        correlation_id=correlation_id,
    )


@dataclass(frozen=True, slots=True)
class FinalizeManifestResult:
    manifest: AudioJobManifest
    stored: StoredAudioObject | None
    asset: TranscriptAudioAssetRecord
    skipped: bool


@dataclass(frozen=True, slots=True)
class FinalizeFinalResult:
    stored: StoredAudioObject | None
    asset: TranscriptAudioAssetRecord
    skipped: bool
    checksum_sha256: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class FinalizeMasterResult:
    stored: StoredAudioObject | None
    asset: TranscriptAudioAssetRecord
    skipped: bool
    checksum_sha256: str
    byte_size: int


def _completed_chunks(
    chunks: list[TranscriptAudioChunkRecord],
) -> list[TranscriptAudioChunkRecord]:
    return [
        chunk
        for chunk in sorted(chunks, key=lambda item: item.chunk_index)
        if chunk.status is AudioChunkStatus.COMPLETED and chunk.output_object_key
    ]


def _holds_from_job_metadata(job: TranscriptAudioJobRecord) -> list[HoldSpec]:
    """Load intercalation holds from mapped pause plan metadata, if present."""
    raw = (job.metadata_json or {}).get(MAPPED_PAUSE_PLAN_KEY)
    if not raw:
        return []
    try:
        mapped = (
            raw
            if isinstance(raw, MappedPausePlan)
            else MappedPausePlan.model_validate(raw)
        )
    except Exception as exc:  # noqa: BLE001
        raise FinalAudioMergeError(
            f"audio job {job.id} has invalid mapped_pause_plan metadata: {exc}"
        ) from exc
    return [(hold.after_chunk_index, hold.hold_seconds) for hold in mapped.holds]


def finalize_audio_job_manifest(
    session: Session,
    repo: AudioJobRepository,
    job: TranscriptAudioJobRecord,
    chunks: list[TranscriptAudioChunkRecord],
    *,
    correlation_id: str | None = None,
    s3_client=None,
    final_asset: TranscriptAudioAssetRecord | None = None,
    master_asset: TranscriptAudioAssetRecord | None = None,
) -> FinalizeManifestResult:
    """Build manifest JSON, persist to S3, and register manifest asset row."""
    final_kwargs = {}
    if final_asset is not None:
        final_kwargs = {
            "final_object_key": final_asset.object_key,
            "final_asset_id": str(final_asset.id),
            "final_checksum_sha256": final_asset.checksum,
            "final_byte_size": final_asset.byte_size,
        }

    master_kwargs = {}
    if master_asset is not None:
        master_metadata = master_asset.metadata_json or {}
        master_kwargs = {
            "master_object_key": master_asset.object_key,
            "master_asset_id": str(master_asset.id),
            "master_checksum_sha256": master_asset.checksum,
            "master_byte_size": master_asset.byte_size,
            "background_profile_code": master_metadata.get("background_profile_code"),
            "background_track_key": master_metadata.get("background_track_key"),
        }

    manifest = build_audio_job_manifest(
        job,
        chunks,
        correlation_id=correlation_id,
        **final_kwargs,
        **master_kwargs,
    )
    object_key = manifest_object_key(job.tenant_id, job.transcript_id, job.id)

    existing = repo.find_manifest_asset(session, job.id)
    if existing is not None and job.status is AudioJobStatus.COMPLETED:
        existing_final_asset_id = (existing.metadata_json or {}).get("final_asset_id")
        if final_asset is None:
            log_tts_manifest_finalized(
                audio_job_id=str(job.id),
                transcript_id=str(job.transcript_id),
                object_key=existing.object_key,
                asset_id=str(existing.id),
                skipped=True,
                chunk_count=manifest.chunk_count,
            )
            repo.record_audio_event(
                session,
                job.id,
                MANIFEST_SKIPPED_EVENT,
                {
                    "object_key": existing.object_key,
                    "asset_id": str(existing.id),
                    "reason": "manifest_already_registered",
                },
                correlation_id=correlation_id,
            )
            return FinalizeManifestResult(
                manifest=manifest,
                stored=None,
                asset=existing,
                skipped=True,
            )
        if existing_final_asset_id == str(final_asset.id):
            log_tts_manifest_finalized(
                audio_job_id=str(job.id),
                transcript_id=str(job.transcript_id),
                object_key=existing.object_key,
                asset_id=str(existing.id),
                skipped=True,
                chunk_count=manifest.chunk_count,
            )
            repo.record_audio_event(
                session,
                job.id,
                MANIFEST_SKIPPED_EVENT,
                {
                    "object_key": existing.object_key,
                    "asset_id": str(existing.id),
                    "reason": "manifest_already_includes_final_asset",
                    "final_asset_id": existing_final_asset_id,
                },
                correlation_id=correlation_id,
            )
            return FinalizeManifestResult(
                manifest=manifest,
                stored=None,
                asset=existing,
                skipped=True,
            )

    json_bytes = manifest.to_json_bytes()
    try:
        stored = write_json_object(
            object_key=object_key,
            payload=json_bytes,
            checksum_sha256=manifest.checksum_sha256,
            s3_client=s3_client,
            metadata={
                "audio-job-id": str(job.id),
                "transcript-id": str(job.transcript_id),
                "schema-version": manifest.schema_version,
            },
        )
    except Exception as exc:
        _log_and_reraise_storage_failure(
            exc,
            job=job,
            object_key=object_key,
            correlation_id=correlation_id,
            artifact_kind="manifest",
        )
        raise

    if existing is not None:
        asset = repo.update_audio_asset(
            session,
            existing.id,
            checksum=manifest.checksum_sha256,
            byte_size=stored.byte_size,
            metadata_json={
                "schema_version": manifest.schema_version,
                "chunk_count": manifest.chunk_count,
                "total_duration_ms": manifest.total_duration_ms,
                "final_asset_id": final_kwargs.get("final_asset_id"),
            },
            correlation_id=correlation_id,
        )
    else:
        asset = repo.create_audio_asset(
            session,
            CreateAudioAssetInput(
                audio_job_id=job.id,
                asset_kind=AudioAssetKind.MANIFEST,
                object_key=stored.object_key,
                mime_type="application/json",
                checksum=manifest.checksum_sha256,
                byte_size=stored.byte_size,
                metadata_json={
                    "schema_version": manifest.schema_version,
                    "chunk_count": manifest.chunk_count,
                    "total_duration_ms": manifest.total_duration_ms,
                    "final_asset_id": final_kwargs.get("final_asset_id"),
                },
            ),
            correlation_id=correlation_id,
        )

    log_tts_manifest_finalized(
        audio_job_id=str(job.id),
        transcript_id=str(job.transcript_id),
        object_key=stored.object_key,
        asset_id=str(asset.id),
        skipped=False,
        chunk_count=manifest.chunk_count,
        total_duration_ms=manifest.total_duration_ms,
        checksum_sha256=manifest.checksum_sha256,
    )
    repo.record_audio_event(
        session,
        job.id,
        MANIFEST_FINALIZED_EVENT,
        {
            "object_key": stored.object_key,
            "asset_id": str(asset.id),
            "checksum_sha256": manifest.checksum_sha256,
            "chunk_count": manifest.chunk_count,
            "total_duration_ms": manifest.total_duration_ms,
            "bucket": stored.bucket,
            "final_asset_id": final_kwargs.get("final_asset_id"),
        },
        correlation_id=correlation_id,
    )

    return FinalizeManifestResult(
        manifest=manifest,
        stored=stored,
        asset=asset,
        skipped=False,
    )


def finalize_audio_job_final(
    session: Session,
    repo: AudioJobRepository,
    job: TranscriptAudioJobRecord,
    chunks: list[TranscriptAudioChunkRecord],
    *,
    correlation_id: str | None = None,
    s3_client=None,
    merge_fn: MergeFn | None = None,
    merge_with_holds_fn=None,
) -> FinalizeFinalResult:
    """Download chunk MP3s, merge to final.mp3, persist asset row, and set final_asset_id."""
    completed = _completed_chunks(chunks)
    if not completed:
        raise FinalAudioMergeError(f"audio job {job.id} has no completed chunks for final merge")

    existing = repo.find_final_asset(session, job.id)
    if existing is not None:
        if job.final_asset_id is None:
            repo.set_job_final_asset_id(
                session,
                job.id,
                existing.id,
                correlation_id=correlation_id,
            )
        log_tts_final_merged(
            audio_job_id=str(job.id),
            transcript_id=str(job.transcript_id),
            object_key=existing.object_key,
            asset_id=str(existing.id),
            skipped=True,
            byte_size=existing.byte_size,
        )
        repo.record_audio_event(
            session,
            job.id,
            FINAL_SKIPPED_EVENT,
            {
                "object_key": existing.object_key,
                "asset_id": str(existing.id),
                "reason": "final_already_registered",
            },
            correlation_id=correlation_id,
        )
        return FinalizeFinalResult(
            stored=None,
            asset=existing,
            skipped=True,
            checksum_sha256=existing.checksum or "",
            byte_size=existing.byte_size or 0,
        )

    chunk_payloads: list[bytes] = []
    for chunk in completed:
        try:
            chunk_payloads.append(
                read_object_bytes(
                    object_key=chunk.output_object_key or "",
                    s3_client=s3_client,
                )
            )
        except Exception as exc:
            _log_and_reraise_storage_failure(
                exc,
                job=job,
                object_key=chunk.output_object_key or "",
                correlation_id=correlation_id,
                artifact_kind="chunk",
            )
            raise

    holds = _holds_from_job_metadata(job)
    hold_count = len(holds)
    total_hold_seconds = sum(seconds for _, seconds in holds)
    try:
        if holds:
            merger_with_holds = merge_with_holds_fn or merge_mp3_chunks_with_holds
            merged_bytes = merger_with_holds(chunk_payloads, holds)
            merge_strategy = "ffmpeg_concat_reencode_with_holds"
        else:
            merger = merge_fn or merge_mp3_chunks
            merged_bytes = merger(chunk_payloads)
            merge_strategy = "ffmpeg_concat_reencode"
    except FinalMergeError as exc:
        raise FinalAudioMergeError(str(exc)) from exc

    checksum_sha256 = hashlib.sha256(merged_bytes).hexdigest()
    object_key = final_object_key(job.tenant_id, job.transcript_id, job.id)
    try:
        stored = write_audio_object(
            object_key=object_key,
            audio_bytes=merged_bytes,
            checksum_sha256=checksum_sha256,
            mime_type="audio/mpeg",
            s3_client=s3_client,
            metadata={
                "audio-job-id": str(job.id),
                "transcript-id": str(job.transcript_id),
                "chunk-count": str(len(completed)),
                "hold-count": str(hold_count),
                "total-hold-seconds": str(total_hold_seconds),
            },
        )
    except Exception as exc:
        _log_and_reraise_storage_failure(
            exc,
            job=job,
            object_key=object_key,
            correlation_id=correlation_id,
            artifact_kind="final",
        )
        raise

    asset = repo.create_audio_asset(
        session,
        CreateAudioAssetInput(
            audio_job_id=job.id,
            asset_kind=AudioAssetKind.FINAL,
            object_key=stored.object_key,
            mime_type=stored.mime_type,
            checksum=checksum_sha256,
            byte_size=stored.byte_size,
            metadata_json={
                "chunk_count": len(completed),
                "merge_strategy": merge_strategy,
                "hold_count": hold_count,
                "total_hold_seconds": total_hold_seconds,
            },
        ),
        correlation_id=correlation_id,
    )
    repo.set_job_final_asset_id(
        session,
        job.id,
        asset.id,
        correlation_id=correlation_id,
    )

    log_tts_final_merged(
        audio_job_id=str(job.id),
        transcript_id=str(job.transcript_id),
        object_key=stored.object_key,
        asset_id=str(asset.id),
        skipped=False,
        byte_size=stored.byte_size,
        checksum_sha256=checksum_sha256,
        chunk_count=len(completed),
    )
    repo.record_audio_event(
        session,
        job.id,
        FINAL_MERGED_EVENT,
        {
            "object_key": stored.object_key,
            "asset_id": str(asset.id),
            "checksum_sha256": checksum_sha256,
            "byte_size": stored.byte_size,
            "bucket": stored.bucket,
            "chunk_count": len(completed),
            "hold_count": hold_count,
            "total_hold_seconds": total_hold_seconds,
            "merge_strategy": merge_strategy,
        },
        correlation_id=correlation_id,
    )

    return FinalizeFinalResult(
        stored=stored,
        asset=asset,
        skipped=False,
        checksum_sha256=checksum_sha256,
        byte_size=stored.byte_size,
    )


def finalize_audio_job_master(
    session: Session,
    repo: AudioJobRepository,
    job: TranscriptAudioJobRecord,
    *,
    correlation_id: str | None = None,
    s3_client=None,
    mix_fn: MixFn | None = None,
) -> FinalizeMasterResult:
    """Mix a curated background bed under the FINAL narration into a MASTER asset.

    Idempotent: if a MASTER asset already exists it is returned unchanged. Fails
    loudly (never a voice-only master) when FINAL or the bed track is missing.
    """
    existing = repo.find_master_asset(session, job.id)
    if existing is not None:
        metadata = existing.metadata_json or {}
        log_tts_master_mixed(
            audio_job_id=str(job.id),
            transcript_id=str(job.transcript_id),
            object_key=existing.object_key,
            asset_id=str(existing.id),
            skipped=True,
            byte_size=existing.byte_size,
            checksum_sha256=existing.checksum or "",
            background_profile_code=metadata.get("background_profile_code"),
            background_track_key=metadata.get("background_track_key"),
        )
        repo.record_audio_event(
            session,
            job.id,
            MASTER_SKIPPED_EVENT,
            {
                "object_key": existing.object_key,
                "asset_id": str(existing.id),
                "reason": "master_already_registered",
            },
            correlation_id=correlation_id,
        )
        return FinalizeMasterResult(
            stored=None,
            asset=existing,
            skipped=True,
            checksum_sha256=existing.checksum or "",
            byte_size=existing.byte_size or 0,
        )

    final_asset = repo.find_final_asset(session, job.id)
    if final_asset is None:
        raise FinalAudioMergeError(
            f"final narration asset missing before background mix for job {job.id}"
        )

    profile = resolve_background_profile(
        tenant_id=job.tenant_id,
        metadata_json=job.metadata_json,
    )

    try:
        narration_bytes = read_object_bytes(
            object_key=final_asset.object_key,
            s3_client=s3_client,
        )
    except Exception as exc:
        _log_and_reraise_storage_failure(
            exc,
            job=job,
            object_key=final_asset.object_key,
            correlation_id=correlation_id,
            artifact_kind="final",
        )
        raise

    try:
        bed_bytes = read_object_bytes(
            object_key=profile.track_object_key,
            s3_client=s3_client,
        )
    except Exception as exc:
        _log_and_reraise_storage_failure(
            exc,
            job=job,
            object_key=profile.track_object_key,
            correlation_id=correlation_id,
            artifact_kind="background_bed",
        )
        raise

    # Optional signature bell — only fetched when the profile configures one, so
    # profiles without a chime never touch S3 for it or change mixer call shape.
    mixer_kwargs: dict[str, bytes] = {}
    if profile.intro_chime_object_key:
        try:
            mixer_kwargs["intro_chime_bytes"] = read_object_bytes(
                object_key=profile.intro_chime_object_key,
                s3_client=s3_client,
            )
        except Exception as exc:
            _log_and_reraise_storage_failure(
                exc,
                job=job,
                object_key=profile.intro_chime_object_key,
                correlation_id=correlation_id,
                artifact_kind="intro_chime",
            )
            raise
    if profile.outro_chime_object_key:
        try:
            mixer_kwargs["outro_chime_bytes"] = read_object_bytes(
                object_key=profile.outro_chime_object_key,
                s3_client=s3_client,
            )
        except Exception as exc:
            _log_and_reraise_storage_failure(
                exc,
                job=job,
                object_key=profile.outro_chime_object_key,
                correlation_id=correlation_id,
                artifact_kind="outro_chime",
            )
            raise

    mixer = mix_fn or mix_background
    try:
        master_bytes = mixer(narration_bytes, bed_bytes, profile, **mixer_kwargs)
    except BackgroundMixError as exc:
        raise FinalAudioMergeError(f"background mix failed for job {job.id}: {exc}") from exc

    checksum_sha256 = hashlib.sha256(master_bytes).hexdigest()
    object_key = master_object_key(job.tenant_id, job.transcript_id, job.id)
    try:
        stored = write_audio_object(
            object_key=object_key,
            audio_bytes=master_bytes,
            checksum_sha256=checksum_sha256,
            mime_type="audio/mpeg",
            s3_client=s3_client,
            metadata={
                "audio-job-id": str(job.id),
                "background-profile-code": profile.code,
            },
        )
    except Exception as exc:
        _log_and_reraise_storage_failure(
            exc,
            job=job,
            object_key=object_key,
            correlation_id=correlation_id,
            artifact_kind="master",
        )
        raise

    merge_strategy = "ffmpeg_sidechain_duck" if profile.duck else "ffmpeg_amix"
    asset = repo.create_audio_asset(
        session,
        CreateAudioAssetInput(
            audio_job_id=job.id,
            asset_kind=AudioAssetKind.MASTER,
            object_key=stored.object_key,
            mime_type=stored.mime_type,
            checksum=checksum_sha256,
            byte_size=stored.byte_size,
            metadata_json={
                "background_profile_code": profile.code,
                "background_track_key": profile.track_object_key,
                "gain_db": profile.gain_db,
                "duck": profile.duck,
                "merge_strategy": merge_strategy,
                "source_final_asset_id": str(final_asset.id),
            },
        ),
        correlation_id=correlation_id,
    )

    log_tts_master_mixed(
        audio_job_id=str(job.id),
        transcript_id=str(job.transcript_id),
        object_key=stored.object_key,
        asset_id=str(asset.id),
        skipped=False,
        byte_size=stored.byte_size,
        checksum_sha256=checksum_sha256,
        background_profile_code=profile.code,
        background_track_key=profile.track_object_key,
    )
    repo.record_audio_event(
        session,
        job.id,
        MASTER_MIXED_EVENT,
        {
            "object_key": stored.object_key,
            "asset_id": str(asset.id),
            "checksum_sha256": checksum_sha256,
            "byte_size": stored.byte_size,
            "bucket": stored.bucket,
            "background_profile_code": profile.code,
            "background_track_key": profile.track_object_key,
            "source_final_asset_id": str(final_asset.id),
        },
        correlation_id=correlation_id,
    )

    return FinalizeMasterResult(
        stored=stored,
        asset=asset,
        skipped=False,
        checksum_sha256=checksum_sha256,
        byte_size=stored.byte_size,
    )
