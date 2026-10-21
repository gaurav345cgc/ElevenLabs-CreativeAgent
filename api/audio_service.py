"""Read operations for TTS audio job API routes."""

from __future__ import annotations

import json
import logging
from uuid import UUID

from db.exceptions import AudioJobNotFoundError
from db.repositories import AudioJobRepository
from db.session import session_scope
from models.messages import TtsAudioJobMessage
from models.requests import CreateAudioJobApiRequest
from models.responses import AudioJobManifestResponse, AudioJobStatusResponse, CreateAudioJobResponse
from observability.logging import log_api_event
from queues.tts_publisher import SqsTtsPublisher, TtsQueuePublisher
from tts_pipeline.intake import AudioJobIntakeService, CreateAudioJobRequest, IntakeValidationError
from tts_pipeline.finalizer.manifest import pause_plan_summary_from_metadata
from tts_pipeline.persistence.s3_audio import generate_presigned_object_url, read_object_bytes


class AudioJobApiService:
    def __init__(
        self,
        *,
        repository: AudioJobRepository,
        intake: AudioJobIntakeService | None = None,
        publisher: TtsQueuePublisher | None = None,
    ) -> None:
        self._repository = repository
        self._intake = intake or AudioJobIntakeService(repository._session_factory)
        self._publisher = publisher

    def create_audio_job(
        self,
        request: CreateAudioJobApiRequest,
        *,
        enqueue: bool = True,
    ) -> CreateAudioJobResponse:
        try:
            result = self._intake.create_audio_job(
                CreateAudioJobRequest(
                    tenant_id=request.tenant_id,
                    transcript_id=request.transcript_id,
                    transcript_version_id=request.transcript_version_id,
                    voice_profile_code=request.voice_profile_code,
                    seed_override=request.seed_override,
                    correlation_id=request.correlation_id,
                )
            )
        except IntakeValidationError as exc:
            log_api_event(
                "audio job intake validation failed",
                level=logging.ERROR,
                event_type="audio_job_validation_failed",
                transcript_id=str(request.transcript_id),
                error=str(exc),
                correlation_id=request.correlation_id,
            )
            raise ValueError(str(exc)) from exc

        queue_message_id = None
        if enqueue:
            publisher = self._publisher or SqsTtsPublisher()
            queue_message_id = publisher.publish(
                TtsAudioJobMessage.from_audio_job_id(
                    audio_job_id=result.audio_job.id,
                    tenant_id=result.audio_job.tenant_id,
                    correlation_id=request.correlation_id,
                )
            )

        job = result.audio_job
        log_api_event(
            "audio job created",
            event_type="audio_job_created",
            audio_job_id=str(job.id),
            transcript_id=str(job.transcript_id),
            transcript_version_id=str(job.transcript_version_id),
            created=result.created,
            queue_message_id=queue_message_id,
            status=job.status.value if hasattr(job.status, "value") else str(job.status),
            correlation_id=request.correlation_id,
        )
        return CreateAudioJobResponse(
            audio_job_id=job.id,
            transcript_id=job.transcript_id,
            transcript_version_id=job.transcript_version_id,
            tenant_id=job.tenant_id,
            status=job.status.value if hasattr(job.status, "value") else str(job.status),
            voice_id=job.voice_id,
            model_id=job.model_id,
            output_format=job.output_format,
            created=result.created,
            queue_message_id=queue_message_id,
            correlation_id=request.correlation_id,
        )

    def get_audio_job_status(
        self,
        audio_job_id: UUID,
        *,
        tenant_id: UUID,
    ) -> AudioJobStatusResponse:
        with session_scope(self._repository._session_factory) as session:
            job = self._repository.get_audio_job(session, audio_job_id)
            if job is None:
                raise AudioJobNotFoundError(f"audio job {audio_job_id} not found")
            if job.tenant_id != tenant_id:
                raise PermissionError("tenant mismatch")

            manifest_asset = self._repository.find_manifest_asset(session, audio_job_id)
            master_asset = self._repository.find_master_asset(session, audio_job_id)
            pause_summary = pause_plan_summary_from_metadata(job.metadata_json)
            return AudioJobStatusResponse(
                audio_job_id=job.id,
                transcript_id=job.transcript_id,
                transcript_version_id=job.transcript_version_id,
                tenant_id=job.tenant_id,
                status=job.status.value if hasattr(job.status, "value") else str(job.status),
                voice_id=job.voice_id,
                model_id=job.model_id,
                output_format=job.output_format,
                total_chunks=job.total_chunks,
                completed_chunks=job.completed_chunks,
                failed_chunks=job.failed_chunks,
                last_error=job.last_error,
                final_asset_id=job.final_asset_id,
                master_asset_id=master_asset.id if master_asset else None,
                manifest_asset_id=manifest_asset.id if manifest_asset else None,
                pause_hold_count=(
                    int(pause_summary["hold_count"]) if pause_summary is not None else None
                ),
                pause_total_hold_seconds=(
                    int(pause_summary["total_hold_seconds"]) if pause_summary is not None else None
                ),
                created_at=job.created_at,
                updated_at=job.updated_at,
                finished_at=job.finished_at,
            )

    def get_audio_job_manifest(
        self,
        audio_job_id: UUID,
        *,
        tenant_id: UUID,
        include_urls: bool = False,
        url_expires_in: int = 3600,
        s3_client=None,
    ) -> AudioJobManifestResponse:
        with session_scope(self._repository._session_factory) as session:
            job = self._repository.get_audio_job(session, audio_job_id)
            if job is None:
                raise AudioJobNotFoundError(f"audio job {audio_job_id} not found")
            if job.tenant_id != tenant_id:
                raise PermissionError("tenant mismatch")

            manifest_asset = self._repository.find_manifest_asset(session, audio_job_id)
            if manifest_asset is None:
                raise ValueError(f"audio job {audio_job_id} has no manifest asset")

            payload_bytes = read_object_bytes(
                object_key=manifest_asset.object_key,
                s3_client=s3_client,
            )
            manifest = json.loads(payload_bytes.decode("utf-8"))

            final_asset = self._repository.find_final_asset(session, audio_job_id)
            final_object_key = final_asset.object_key if final_asset else manifest.get("final_object_key")
            final_asset_id = job.final_asset_id or (final_asset.id if final_asset else None)

            master_asset = self._repository.find_master_asset(session, audio_job_id)
            master_object_key = manifest.get("master_object_key") or (
                master_asset.object_key if master_asset else None
            )
            master_asset_id = master_asset.id if master_asset else None

            manifest_url = None
            final_url = None
            master_url = None
            if include_urls:
                manifest_url = generate_presigned_object_url(
                    object_key=manifest_asset.object_key,
                    expires_in=url_expires_in,
                    s3_client=s3_client,
                )
                if final_object_key:
                    final_url = generate_presigned_object_url(
                        object_key=final_object_key,
                        expires_in=url_expires_in,
                        s3_client=s3_client,
                    )
                if master_object_key:
                    master_url = generate_presigned_object_url(
                        object_key=master_object_key,
                        expires_in=url_expires_in,
                        s3_client=s3_client,
                    )

            return AudioJobManifestResponse(
                audio_job_id=job.id,
                transcript_id=job.transcript_id,
                tenant_id=job.tenant_id,
                manifest_asset_id=manifest_asset.id,
                manifest_object_key=manifest_asset.object_key,
                final_asset_id=final_asset_id,
                final_object_key=final_object_key,
                master_asset_id=master_asset_id,
                master_object_key=master_object_key,
                manifest=manifest,
                manifest_url=manifest_url,
                final_url=final_url,
                master_url=master_url,
            )
