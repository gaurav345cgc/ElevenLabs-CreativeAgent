"""Catalog browser: completed audio jobs joined with transcript taxonomy."""

from __future__ import annotations

from uuid import UUID

from db.repositories import AudioJobRepository, TranscriptRepository
from db.session import session_scope
from models.requests import RetainLibraryRequest
from models.responses import LibraryItem, LibraryResponse, RetainLibraryResponse
from transcript_composer.title import GENERATION_DISPLAY, WOUND_DISPLAY, build_title_from_taxonomy
from tts_pipeline.finalizer.manifest import pause_plan_summary_from_metadata

PILLAR_DISPLAY: dict[str, str] = {
    "p01": "Pillar P01",
    "p02": "Pillar P02",
    "p03": "Pillar P03",
    "p04": "Pillar P04",
    "p05": "Pillar P05",
}


def _pillar_label(code: str | None) -> str | None:
    if not code:
        return None
    key = code.strip().lower()
    return PILLAR_DISPLAY.get(key, key.upper())


def _generation_label(code: str | None) -> str | None:
    if not code:
        return None
    key = code.strip().lower()
    return GENERATION_DISPLAY.get(key, key.replace("_", " ").title())


def _wound_label(code: str | None) -> str | None:
    if not code:
        return None
    key = code.strip().lower()
    return WOUND_DISPLAY.get(key, key.replace("_", " "))


class LibraryApiService:
    def __init__(
        self,
        *,
        transcript_repository: TranscriptRepository,
        audio_repository: AudioJobRepository,
    ) -> None:
        self._transcripts = transcript_repository
        self._audio = audio_repository

    def list_library(self, *, tenant_id: UUID) -> LibraryResponse:
        with session_scope(self._transcripts._session_factory) as session:
            jobs = self._audio.list_latest_completed_jobs_for_tenant(session, tenant_id)
            items: list[LibraryItem] = []
            for job in jobs:
                transcript = self._transcripts.get_transcript(session, job.transcript_id)
                if transcript is None or transcript.tenant_id != tenant_id:
                    continue
                _, versions = self._transcripts.load_transcript_with_versions(
                    session, job.transcript_id
                )
                from api.transcript_service import _title_and_duration

                title, duration = _title_and_duration(transcript, versions)
                if not title:
                    title = build_title_from_taxonomy(
                        transcript.generation_code,
                        transcript.wound_id,
                        transcript.stage_no,
                    )
                pause_summary = pause_plan_summary_from_metadata(job.metadata_json)
                items.append(
                    LibraryItem(
                        transcript_id=transcript.id,
                        audio_job_id=job.id,
                        title=title,
                        status=transcript.status,
                        content_type=transcript.content_type,
                        generation_code=transcript.generation_code,
                        generation_label=_generation_label(transcript.generation_code),
                        wound_id=transcript.wound_id,
                        wound_label=_wound_label(transcript.wound_id),
                        stage_no=transcript.stage_no,
                        pillar_code=transcript.pillar_code,
                        pillar_label=_pillar_label(transcript.pillar_code),
                        pause_hold_count=(
                            int(pause_summary["hold_count"]) if pause_summary else None
                        ),
                        pause_total_hold_seconds=(
                            int(pause_summary["total_hold_seconds"]) if pause_summary else None
                        ),
                        duration_estimate=duration,
                        finished_at=job.finished_at,
                        created_at=transcript.created_at,
                        updated_at=transcript.updated_at,
                    )
                )

            items.sort(
                key=lambda item: (
                    item.pillar_code or "zzz",
                    item.generation_code or "zzz",
                    item.wound_id or "zzz",
                    -(item.finished_at or item.updated_at).timestamp()
                    if (item.finished_at or item.updated_at)
                    else 0,
                )
            )

            return LibraryResponse(
                tenant_id=tenant_id,
                item_count=len(items),
                items=items,
            )

    def retain_library(
        self,
        *,
        tenant_id: UUID,
        request: RetainLibraryRequest,
    ) -> RetainLibraryResponse:
        keep = set(request.transcript_ids)
        with session_scope(self._transcripts._session_factory) as session:
            archived = self._audio.archive_completed_jobs_except_transcripts(
                session,
                tenant_id=tenant_id,
                keep_transcript_ids=keep,
            )
            remaining = self._audio.list_latest_completed_jobs_for_tenant(session, tenant_id)
            return RetainLibraryResponse(
                tenant_id=tenant_id,
                kept_transcript_ids=sorted(keep, key=str),
                archived_job_count=archived,
                remaining_item_count=len(remaining),
            )
