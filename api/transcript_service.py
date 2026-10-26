"""Read and retry operations for the intake API."""

from __future__ import annotations

import logging
import time
from uuid import UUID

from db.repositories import TranscriptRepository
from db.session import session_scope
from models.enums import EnhancementMode, TranscriptStatus, VersionKind
from models.messages import EnhancementJobMessage
from models.metadata import DurationEstimate
from models.requests import CreateAudioJobApiRequest, RetryEnhancementRequest
from models.responses import (
    ClearPendingReviewResponse,
    RetryEnhancementResponse,
    TranscriptStatusResponse,
    TranscriptVersionItem,
    TranscriptVersionsResponse,
    TranscriptWaitResponse,
)
from queues.publisher import EnhancementQueuePublisher, SqsEnhancementPublisher
from queues.tts_publisher import TtsQueuePublisher
from observability.logging import log_api_event
from sqlalchemy import select
from db.orm import TranscriptJobEventRow
from transcript_composer.title import build_title_from_taxonomy
from tts_pipeline.pause_planner.draft import (
    create_draft_pause_plan,
    create_local_draft_pause_plan,
    load_draft_pause_plan,
    pause_plan_from_audio_job,
)
from tts_pipeline.pause_planner.human_markers import (
    DRAFT_PAUSE_PLAN_KEY,
    HUMAN_PAUSE_PLAN_KEY,
    HumanPauseMarkerError,
    build_human_pause_plan,
    build_pause_review_text,
    load_human_pause_plan,
    parse_pause_marked_text,
)
from db.repositories import AudioJobRepository
from tts_pipeline.pause_planner.errors import PausePlannerError
from tts_pipeline.pause_planner.policy import PAUSE_POLICY_VERSION
from tts_pipeline.background_policy import (
    BACKGROUND_PROFILE_CODE_KEY,
    BACKGROUND_SELECTION_KEY,
    BackgroundPolicyError,
    apply_reviewer_background_choice,
    load_background_selection,
    select_background_for_script,
)
from tts_pipeline.voice_policy import DEFAULT_VOICE_PROFILE_CODE
from api.audio_service import AudioJobApiService


_RETRYABLE_STATUSES = frozenset(
    {
        TranscriptStatus.FAILED_ENHANCEMENT,
        TranscriptStatus.REVIEW_REQUIRED,
    }
)

_TERMINAL_FAILURE_STATUSES = frozenset(
    {
        TranscriptStatus.FAILED_ENHANCEMENT,
        TranscriptStatus.REVIEW_REQUIRED,
    }
)

_DEFAULT_WAIT_POLL_SECONDS = 2.0


class TranscriptApiService:
    def __init__(
        self,
        *,
        repository: TranscriptRepository,
        publisher: EnhancementQueuePublisher | None = None,
        audio_job_service: AudioJobApiService | None = None,
        tts_publisher: TtsQueuePublisher | None = None,
    ) -> None:
        self._repository = repository
        self._publisher = publisher or SqsEnhancementPublisher()
        # Injected for tests; production builds a real AudioJobApiService on demand.
        self._audio_job_service = audio_job_service
        self._tts_publisher = tts_publisher

    def get_transcript_status(
        self,
        transcript_id: UUID,
        *,
        tenant_id: UUID,
    ) -> TranscriptStatusResponse:
        with session_scope(self._repository._session_factory) as session:
            transcript, versions = self._repository.load_transcript_with_versions(
                session,
                transcript_id,
            )
            if transcript.tenant_id != tenant_id:
                raise PermissionError("tenant mismatch")

            title, duration = _title_and_duration(transcript, versions)
            return TranscriptStatusResponse(
                transcript_id=transcript.id,
                tenant_id=transcript.tenant_id,
                status=transcript.status,
                title=title,
                current_version_id=transcript.current_version_id,
                enhancement_attempt_count=transcript.enhancement_attempt_count,
                last_error=transcript.last_error,
                content_type=transcript.content_type,
                generation_code=transcript.generation_code,
                wound_id=transcript.wound_id,
                stage_no=transcript.stage_no,
                pillar_code=transcript.pillar_code,
                duration_estimate=duration,
                created_at=transcript.created_at,
                updated_at=transcript.updated_at,
            )

    def list_versions(
        self,
        transcript_id: UUID,
        *,
        tenant_id: UUID,
        include_content: bool = False,
    ) -> TranscriptVersionsResponse:
        with session_scope(self._repository._session_factory) as session:
            transcript, versions = self._repository.load_transcript_with_versions(
                session,
                transcript_id,
            )
            if transcript.tenant_id != tenant_id:
                raise PermissionError("tenant mismatch")

            if include_content:
                versions = [
                    self._ensure_draft_pause_preview(session, version)
                    for version in versions
                ]
                versions = self._ensure_background_selections(session, transcript, versions)

            items = [
                TranscriptVersionItem(
                    version_id=version.id,
                    version_kind=version.version_kind,
                    created_at=version.created_at,
                    created_by_agent=version.created_by_agent,
                    source_version_id=version.source_version_id,
                    enhancement_mode=version.enhancement_mode,
                    content_text=version.content_text if include_content else None,
                    content_json=version.content_json if include_content else None,
                    pause_review_text=(
                        build_pause_review_text(
                            content_text=version.content_text,
                            content_json=version.content_json,
                            metadata_json=version.metadata_json,
                        )
                        if include_content
                        else None
                    ),
                    metadata_json=_with_background_preview_urls(version.metadata_json or {})
                    if include_content
                    else (version.metadata_json or {}),
                )
                for version in versions
            ]
            return TranscriptVersionsResponse(
                transcript_id=transcript_id,
                versions=items,
            )

    def _ensure_draft_pause_preview(self, session, version):
        """Attach OpenAI (or prior job) pause markers for Script Hub when missing.

        Preference: human plan > cached draft > audio-job pause_plan > new OpenAI draft.
        Failures are non-fatal — editor still loads unmarked text.
        """
        if version.version_kind not in {
            VersionKind.ELEVENLABS_ENHANCED,
            VersionKind.APPROVED_FINAL,
        }:
            return version

        meta = version.metadata_json or {}
        human = load_human_pause_plan(meta)
        if human is not None and human.holds:
            return version
        existing_draft = load_draft_pause_plan(meta)
        # Empty drafts (e.g. speech overshot wall-clock and old policy wiped holds)
        # must be regenerated so Script Hub shows [pause Ns] markers.
        # Also regenerate when pause policy version advances (e.g. denser sentence holds).
        if (
            existing_draft is not None
            and existing_draft.holds
            and existing_draft.policy_version == PAUSE_POLICY_VERSION
        ):
            return version

        audio_repo = AudioJobRepository(self._repository._session_factory)
        existing_job = audio_repo.find_latest_audio_job_for_version(session, version.id)
        from_job = pause_plan_from_audio_job(existing_job)
        if (
            from_job is not None
            and from_job.holds
            and from_job.policy_version == PAUSE_POLICY_VERSION
        ):
            return self._repository.merge_transcript_version_metadata(
                session,
                version.id,
                {
                    DRAFT_PAUSE_PLAN_KEY: from_job.model_dump(mode="json"),
                    "draft_pause_source": "audio_job",
                    "draft_pause_hold_count": len(from_job.holds),
                    "draft_pause_total_hold_seconds": from_job.total_hold_seconds,
                },
            )

        try:
            # Script Hub must stay under API Gateway ~29s. OpenAI draft/bed calls
            # routinely blow that budget on long scripts — use local density + default bed.
            draft = create_local_draft_pause_plan(version)
        except (PausePlannerError, Exception) as exc:  # noqa: BLE001
            log_api_event(
                "draft pause plan failed",
                level=logging.WARNING,
                event_type="draft_pause_plan_failed",
                transcript_id=str(version.transcript_id),
                version_id=str(version.id),
                error=str(exc),
            )
            return version

        return self._repository.merge_transcript_version_metadata(
            session,
            version.id,
            {
                DRAFT_PAUSE_PLAN_KEY: draft.model_dump(mode="json"),
                "draft_pause_source": "local_density",
                "draft_pause_hold_count": len(draft.holds),
                "draft_pause_total_hold_seconds": draft.total_hold_seconds,
            },
        )

    def _ensure_background_selections(self, session, transcript, versions):
        """Attach OpenAI catalog bed choice for Script Hub / TTS mix (cached)."""
        eligible = [
            version
            for version in versions
            if version.version_kind
            in {VersionKind.ELEVENLABS_ENHANCED, VersionKind.APPROVED_FINAL}
        ]
        if not eligible:
            return versions

        existing = next(
            (
                load_background_selection(version.metadata_json)
                for version in reversed(eligible)
                if load_background_selection(version.metadata_json) is not None
            ),
            None,
        )
        persist = True
        if existing is None:
            # OpenAI picks from the 28-bed catalog using script + wound/pillar;
            # falls back to calm_ambient_01 when selector is off or unavailable.
            source = next(
                (
                    version
                    for version in reversed(eligible)
                    if (version.content_text or "").strip()
                ),
                eligible[-1],
            )
            title = None
            if isinstance(source.metadata_json, dict):
                raw_title = source.metadata_json.get("title")
                if isinstance(raw_title, str) and raw_title.strip():
                    title = raw_title.strip()
            existing = select_background_for_script(
                content_text=source.content_text or "",
                title=title,
                content_type=transcript.content_type,
                generation_code=transcript.generation_code,
                wound_id=transcript.wound_id,
                stage_no=transcript.stage_no,
                pillar_code=transcript.pillar_code,
            )
            log_api_event(
                "background selection attached for script hub",
                event_type="background_selection_attached",
                transcript_id=str(transcript.id),
                selected_code=existing.get("selected_code"),
                selected_by=existing.get("selected_by"),
            )

        updated: dict = {version.id: version for version in versions}
        for version in eligible:
            if load_background_selection(version.metadata_json) is not None:
                continue
            patch = {
                BACKGROUND_SELECTION_KEY: existing,
                BACKGROUND_PROFILE_CODE_KEY: existing["selected_code"],
            }
            if persist:
                updated[version.id] = self._repository.merge_transcript_version_metadata(
                    session,
                    version.id,
                    patch,
                )
            else:
                updated[version.id] = version.model_copy(
                    update={"metadata_json": {**(version.metadata_json or {}), **patch}}
                )
        return [updated[version.id] for version in versions]

    def set_background_profile(
        self,
        transcript_id: UUID,
        *,
        tenant_id: UUID,
        profile_code: str,
    ) -> TranscriptVersionsResponse:
        """Reviewer overrides the OpenAI bed; persists on latest review version."""
        with session_scope(self._repository._session_factory) as session:
            transcript, versions = self._repository.load_transcript_with_versions(
                session,
                transcript_id,
            )
            if transcript.tenant_id != tenant_id:
                raise PermissionError("tenant mismatch")
            target = next(
                (
                    version
                    for version in reversed(versions)
                    if version.version_kind
                    in {VersionKind.APPROVED_FINAL, VersionKind.ELEVENLABS_ENHANCED}
                ),
                None,
            )
            if target is None:
                raise ValueError("no enhanced or approved version to attach background to")
            try:
                selection = apply_reviewer_background_choice(
                    load_background_selection(target.metadata_json),
                    profile_code,
                )
            except BackgroundPolicyError as exc:
                raise ValueError(str(exc)) from exc
            self._repository.merge_transcript_version_metadata(
                session,
                target.id,
                {
                    BACKGROUND_SELECTION_KEY: selection,
                    BACKGROUND_PROFILE_CODE_KEY: selection["selected_code"],
                },
            )
        return self.list_versions(transcript_id, tenant_id=tenant_id, include_content=True)

    def wait_for_enhanced_transcript(
        self,
        transcript_id: UUID,
        *,
        tenant_id: UUID,
        max_wait_seconds: int = 25,
        poll_interval_seconds: float = _DEFAULT_WAIT_POLL_SECONDS,
        include_content: bool = True,
    ) -> tuple[TranscriptWaitResponse, bool]:
        """Poll until APPROVED, a terminal failure, or max_wait_seconds elapses."""
        deadline = time.monotonic() + max_wait_seconds
        last_status: TranscriptStatusResponse | None = None
        last_logged_status: TranscriptStatus | None = None

        while True:
            last_status = self.get_transcript_status(transcript_id, tenant_id=tenant_id)
            if last_status.status != last_logged_status:
                log_api_event(
                    "transcript wait poll",
                    event_type="transcript_wait_poll",
                    transcript_id=str(transcript_id),
                    status=last_status.status.value,
                )
                last_logged_status = last_status.status
            if last_status.status == TranscriptStatus.APPROVED:
                log_api_event(
                    "transcript approved",
                    event_type="transcript_approved",
                    transcript_id=str(transcript_id),
                )
                return self._build_wait_response(
                    transcript_id,
                    tenant_id=tenant_id,
                    status_response=last_status,
                    include_content=include_content,
                    ready=True,
                ), True
            if last_status.status in _TERMINAL_FAILURE_STATUSES:
                log_api_event(
                    "transcript wait failed status",
                    level=logging.ERROR,
                    event_type="transcript_wait_failed_status",
                    transcript_id=str(transcript_id),
                    status=last_status.status.value,
                    last_error=last_status.last_error,
                )
                return self._build_wait_response(
                    transcript_id,
                    tenant_id=tenant_id,
                    status_response=last_status,
                    include_content=include_content,
                    ready=False,
                ), True

            if time.monotonic() >= deadline:
                return self._build_wait_response(
                    transcript_id,
                    tenant_id=tenant_id,
                    status_response=last_status,
                    include_content=False,
                    ready=False,
                ), False

            time.sleep(poll_interval_seconds)

    def _build_wait_response(
        self,
        transcript_id: UUID,
        *,
        tenant_id: UUID,
        status_response: TranscriptStatusResponse,
        include_content: bool,
        ready: bool,
    ) -> TranscriptWaitResponse:
        raw_text: str | None = None
        enhanced_text: str | None = None
        if include_content and ready:
            versions = self.list_versions(
                transcript_id,
                tenant_id=tenant_id,
                include_content=True,
            )
            for version in versions.versions:
                if version.version_kind == VersionKind.RAW_PATTERN:
                    raw_text = version.content_text
                elif version.version_kind == VersionKind.APPROVED_FINAL:
                    enhanced_text = version.content_text
                elif version.version_kind == VersionKind.ELEVENLABS_ENHANCED and enhanced_text is None:
                    enhanced_text = version.content_text

        return TranscriptWaitResponse(
            **status_response.model_dump(),
            ready=ready,
            raw_content_text=raw_text,
            enhanced_content_text=enhanced_text,
        )

    def retry_enhancement(
        self,
        transcript_id: UUID,
        *,
        tenant_id: UUID,
        body: RetryEnhancementRequest | None = None,
    ) -> RetryEnhancementResponse:
        body = body or RetryEnhancementRequest()
        raw_version_id: UUID
        mode: EnhancementMode
        voice_model: str

        with session_scope(self._repository._session_factory) as session:
            transcript, versions = self._repository.load_transcript_with_versions(
                session,
                transcript_id,
            )
            if transcript.tenant_id != tenant_id:
                raise PermissionError("tenant mismatch")

            if transcript.status not in _RETRYABLE_STATUSES:
                raise ValueError(
                    f"transcript status {transcript.status.value} is not eligible for retry"
                )

            raw_version = _latest_raw_version(versions)
            if raw_version is None:
                raise ValueError("no RAW_PATTERN version found for transcript")

            raw_version_id = raw_version.id
            mode, voice_model = _resolve_retry_handoff(
                session,
                transcript_id,
                body,
            )

            self._repository.update_transcript_status(
                session,
                transcript_id,
                TranscriptStatus.PENDING_ENHANCEMENT,
                correlation_id=body.correlation_id,
            )
            self._repository.record_job_event(
                session,
                transcript_id,
                "ENHANCEMENT_RETRY_REQUESTED",
                {
                    "raw_version_id": str(raw_version_id),
                    "requested_output_mode": mode.value,
                    "voice_model": voice_model,
                },
                correlation_id=body.correlation_id,
            )

        message = EnhancementJobMessage.from_ids(
            transcript_id=transcript_id,
            tenant_id=tenant_id,
            raw_version_id=raw_version_id,
            requested_output_mode=mode,
            voice_model=voice_model,
            correlation_id=body.correlation_id,
        )
        queue_message_id = self._publisher.publish(message)

        log_api_event(
            "enhancement retry enqueued",
            event_type="enhancement_retry",
            transcript_id=str(transcript_id),
            raw_version_id=str(raw_version_id),
            queue_message_id=queue_message_id,
            correlation_id=body.correlation_id,
        )

        return RetryEnhancementResponse(
            transcript_id=transcript_id,
            raw_version_id=raw_version_id,
            status=TranscriptStatus.PENDING_ENHANCEMENT,
            queue_message_id=queue_message_id,
            requested_output_mode=mode,
            voice_model=voice_model,
            correlation_id=body.correlation_id,
        )

    def list_transcripts(
        self,
        *,
        tenant_id: UUID,
        status: TranscriptStatus | None = None,
    ) -> list[TranscriptStatusResponse]:
        with session_scope(self._repository._session_factory) as session:
            transcripts = self._repository.list_transcripts(
                session, status=status, tenant_id=tenant_id
            )
            results = []
            for tx in transcripts:
                _, versions = self._repository.load_transcript_with_versions(session, tx.id)
                title, duration = _title_and_duration(tx, versions)
                results.append(
                    TranscriptStatusResponse(
                        transcript_id=tx.id,
                        tenant_id=tx.tenant_id,
                        status=tx.status,
                        title=title,
                        current_version_id=tx.current_version_id,
                        enhancement_attempt_count=tx.enhancement_attempt_count,
                        last_error=tx.last_error,
                        content_type=tx.content_type,
                        generation_code=tx.generation_code,
                        wound_id=tx.wound_id,
                        stage_no=tx.stage_no,
                        pillar_code=tx.pillar_code,
                        duration_estimate=duration,
                        created_at=tx.created_at,
                        updated_at=tx.updated_at,
                    )
                )
            return results

    def clear_pending_review(
        self,
        *,
        tenant_id: UUID,
    ) -> ClearPendingReviewResponse:
        with session_scope(self._repository._session_factory) as session:
            dismissed = self._repository.dismiss_enhanced_for_tenant(
                session, tenant_id=tenant_id
            )
            return ClearPendingReviewResponse(
                tenant_id=tenant_id,
                dismissed_count=len(dismissed),
                transcript_ids=dismissed,
            )

    def approve_transcript(
        self,
        transcript_id: UUID,
        *,
        tenant_id: UUID,
        approved_text: str | None = None,
        background_profile_code: str | None = None,
        correlation_id: str | None = None,
        enqueue_tts: bool = True,
    ) -> TranscriptStatusResponse:
        with session_scope(self._repository._session_factory) as session:
            transcript, versions = self._repository.load_transcript_with_versions(
                session,
                transcript_id,
            )
            if transcript.tenant_id != tenant_id:
                raise PermissionError("tenant mismatch")

            enhanced_version = next(
                (v for v in reversed(versions) if v.version_kind == VersionKind.ELEVENLABS_ENHANCED),
                None,
            )
            if enhanced_version is None:
                raise ValueError("no ELEVENLABS_ENHANCED version found to approve")

            raw_approved = (
                approved_text if approved_text is not None else enhanced_version.content_text
            )
            try:
                # Always beat-index holds — approve rewrites content_json.beats to match units.
                parsed = parse_pause_marked_text(raw_approved or "", prefer_beats=True)
            except HumanPauseMarkerError as exc:
                raise ValueError(str(exc)) from exc

            human_plan = build_human_pause_plan(parsed)
            final_text = parsed.spoken_text

            content_json = dict(enhanced_version.content_json or {})
            # Keep beat anchors aligned with the units the reviewer paused between.
            content_json["beats"] = list(parsed.speech_units)

            existing_approved = next(
                (
                    v
                    for v in reversed(versions)
                    if v.version_kind == VersionKind.APPROVED_FINAL
                    and v.source_version_id == enhanced_version.id
                ),
                None,
            )
            # Prefer prior APPROVED metadata (beds/pauses) when re-approving.
            metadata_source = (
                existing_approved.metadata_json
                if existing_approved is not None
                else enhanced_version.metadata_json
            )
            metadata_json = dict(metadata_source or {})
            if human_plan.holds:
                metadata_json[HUMAN_PAUSE_PLAN_KEY] = human_plan.model_dump(mode="json")
                metadata_json["human_pause_hold_count"] = len(human_plan.holds)
                metadata_json["human_pause_total_hold_seconds"] = human_plan.total_hold_seconds
            else:
                # No markers → leave auto OpenAI planner in charge for TTS.
                metadata_json.pop(HUMAN_PAUSE_PLAN_KEY, None)
                metadata_json.pop("human_pause_hold_count", None)
                metadata_json.pop("human_pause_total_hold_seconds", None)

            requested_code = (background_profile_code or "").strip() or None
            if requested_code:
                try:
                    selection = apply_reviewer_background_choice(
                        load_background_selection(metadata_json),
                        requested_code,
                    )
                    metadata_json[BACKGROUND_SELECTION_KEY] = selection
                    metadata_json[BACKGROUND_PROFILE_CODE_KEY] = selection["selected_code"]
                except BackgroundPolicyError as exc:
                    raise ValueError(str(exc)) from exc
            else:
                # Keep OpenAI / prior catalog pick locked onto APPROVED_FINAL for TTS mix.
                existing = load_background_selection(metadata_json)
                if existing and existing.get("selected_code"):
                    metadata_json[BACKGROUND_PROFILE_CODE_KEY] = existing["selected_code"]
                    metadata_json[BACKGROUND_SELECTION_KEY] = existing

            if existing_approved is not None:
                # Re-approve updates the same APPROVED_FINAL row (unique on source+mode).
                new_version = self._repository.replace_transcript_version_content(
                    session,
                    existing_approved.id,
                    content_text=final_text,
                    content_json=content_json,
                    metadata_json=metadata_json,
                    correlation_id=correlation_id,
                )
            else:
                from db.repositories.types import InsertTranscriptVersionInput

                version_input = InsertTranscriptVersionInput(
                    transcript_id=transcript_id,
                    version_kind=VersionKind.APPROVED_FINAL,
                    content_text=final_text,
                    content_json=content_json,
                    created_by_agent="reviewer",
                    metadata_json=metadata_json,
                    source_version_id=enhanced_version.id,
                    enhancement_mode=enhanced_version.enhancement_mode,
                )
                new_version = self._repository.insert_transcript_version(
                    session,
                    version_input,
                    correlation_id=correlation_id,
                )

            if transcript.status != TranscriptStatus.APPROVED:
                self._repository.update_transcript_status(
                    session,
                    transcript_id,
                    TranscriptStatus.APPROVED,
                    correlation_id=correlation_id,
                )
            self._repository.set_current_version(
                session,
                transcript_id,
                new_version.id,
                correlation_id=correlation_id,
            )
            self._repository.record_job_event(
                session,
                transcript_id,
                "TRANSCRIPT_APPROVED",
                {
                    "approved_version_id": str(new_version.id),
                    "source_version_id": str(enhanced_version.id),
                    "human_pause_hold_count": len(human_plan.holds),
                    "human_pause_total_hold_seconds": human_plan.total_hold_seconds,
                    "background_profile_code": metadata_json.get(BACKGROUND_PROFILE_CODE_KEY),
                },
                correlation_id=correlation_id,
            )

            updated_tx, updated_versions = self._repository.load_transcript_with_versions(
                session,
                transcript_id,
            )
            title, duration = _title_and_duration(updated_tx, updated_versions)
            status = TranscriptStatusResponse(
                transcript_id=updated_tx.id,
                tenant_id=updated_tx.tenant_id,
                status=updated_tx.status,
                title=title,
                current_version_id=updated_tx.current_version_id,
                enhancement_attempt_count=updated_tx.enhancement_attempt_count,
                last_error=updated_tx.last_error,
                content_type=updated_tx.content_type,
                generation_code=updated_tx.generation_code,
                wound_id=updated_tx.wound_id,
                stage_no=updated_tx.stage_no,
                pillar_code=updated_tx.pillar_code,
                duration_estimate=duration,
                created_at=updated_tx.created_at,
                updated_at=updated_tx.updated_at,
            )
            approved_version_id = new_version.id

        if not enqueue_tts:
            return status

        return self._enqueue_tts_after_approve(
            status,
            approved_version_id=approved_version_id,
            correlation_id=correlation_id,
        )

    def _enqueue_tts_after_approve(
        self,
        status: TranscriptStatusResponse,
        *,
        approved_version_id: UUID,
        correlation_id: str | None,
    ) -> TranscriptStatusResponse:
        """Create + enqueue TTS job for APPROVED_FINAL (pauses + bed already on version)."""
        audio_service = self._audio_job_service or AudioJobApiService(
            repository=AudioJobRepository(self._repository._session_factory),
            publisher=self._tts_publisher,
        )
        try:
            created = audio_service.create_audio_job(
                CreateAudioJobApiRequest(
                    tenant_id=status.tenant_id,
                    transcript_id=status.transcript_id,
                    transcript_version_id=approved_version_id,
                    voice_profile_code=DEFAULT_VOICE_PROFILE_CODE,
                    correlation_id=correlation_id,
                ),
                enqueue=True,
            )
        except Exception as exc:  # noqa: BLE001 — approve already committed; surface TTS failure
            log_api_event(
                "approve TTS enqueue failed",
                level=logging.ERROR,
                event_type="approve_tts_enqueue_failed",
                transcript_id=str(status.transcript_id),
                version_id=str(approved_version_id),
                error=str(exc),
                correlation_id=correlation_id,
            )
            return status.model_copy(update={"tts_enqueue_error": str(exc)})

        log_api_event(
            "approve sent to TTS",
            event_type="approve_tts_enqueued",
            transcript_id=str(status.transcript_id),
            version_id=str(approved_version_id),
            audio_job_id=str(created.audio_job_id),
            queue_message_id=created.queue_message_id,
            correlation_id=correlation_id,
        )
        return status.model_copy(
            update={
                "audio_job_id": created.audio_job_id,
                "tts_queue_message_id": created.queue_message_id,
            }
        )


def _title_and_duration(transcript, versions) -> tuple[str | None, DurationEstimate | None]:
    current = next((v for v in versions if v.id == transcript.current_version_id), None)
    if current is None and versions:
        current = versions[-1]
    if current is None:
        return _fallback_title(transcript), None

    metadata = current.metadata_json or {}
    title = _metadata_title(metadata)
    duration_payload = metadata.get("duration_estimate")
    duration = DurationEstimate.model_validate(duration_payload) if duration_payload else None
    if title:
        return title, duration

    raw = _latest_raw_version(versions)
    if raw is not None:
        raw_title = _metadata_title(raw.metadata_json)
        if raw_title:
            return raw_title, duration

    return _fallback_title(transcript), duration


def _metadata_title(metadata: dict | None) -> str | None:
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get("title")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _fallback_title(transcript) -> str | None:
    if not transcript.generation_code and not transcript.wound_id:
        return None
    return build_title_from_taxonomy(
        transcript.generation_code,
        transcript.wound_id,
        transcript.stage_no,
    )


def _latest_raw_version(versions):
    raw_versions = [v for v in versions if v.version_kind == VersionKind.RAW_PATTERN]
    if not raw_versions:
        return None
    return raw_versions[-1]


def _resolve_retry_handoff(session, transcript_id: UUID, body: RetryEnhancementRequest):
    if body.requested_output_mode and body.voice_model:
        return body.requested_output_mode, body.voice_model

    stmt = (
        select(TranscriptJobEventRow)
        .where(TranscriptJobEventRow.transcript_id == transcript_id)
        .order_by(TranscriptJobEventRow.created_at.desc())
    )
    for row in session.scalars(stmt).all():
        payload = row.event_payload or {}
        if row.event_type in {"TRANSCRIPT_QUEUED", "ENHANCEMENT_RETRY_REQUESTED"}:
            mode = EnhancementMode(
                payload.get("requested_output_mode", EnhancementMode.PLAIN_PASTE.value)
            )
            voice = payload.get("voice_model", "eleven_multilingual_v2")
            return (
                body.requested_output_mode or mode,
                body.voice_model or voice,
            )

    return (
        body.requested_output_mode or EnhancementMode.PLAIN_PASTE,
        body.voice_model or "eleven_multilingual_v2",
    )


def _with_background_preview_urls(metadata_json: dict) -> dict:
    """Attach short-lived S3 preview URLs for Script Hub audio players."""
    selection = load_background_selection(metadata_json)
    if selection is None:
        return metadata_json
    enriched = dict(metadata_json)
    cloned = dict(selection)
    cloned["preview_url"] = _preview_url_for_key(cloned.get("track_object_key"))
    alts = []
    for item in cloned.get("alternatives") or []:
        if not isinstance(item, dict):
            continue
        alt = dict(item)
        alt["preview_url"] = _preview_url_for_key(alt.get("track_object_key"))
        alts.append(alt)
    cloned["alternatives"] = alts
    enriched[BACKGROUND_SELECTION_KEY] = cloned
    return enriched


def _preview_url_for_key(object_key: str | None) -> str | None:
    if not object_key:
        return None
    try:
        from tts_pipeline.persistence.s3_audio import generate_presigned_object_url

        return generate_presigned_object_url(object_key=str(object_key), expires_in=3600)
    except Exception:  # noqa: BLE001
        return None
