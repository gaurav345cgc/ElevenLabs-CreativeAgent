"""HTTP client for Creative Agent intake and status APIs."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from observability.logging import log_orchestrator_event
from pipeline_orchestrator.config import OrchestratorSettings
from pipeline_orchestrator.errors import is_transient_third_party_error

logger = logging.getLogger("creative_agent.orchestrator")


class CreativeAgentApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body: dict[str, Any] = body or {}

    @property
    def validation_report(self) -> dict[str, Any] | None:
        """Compose QA report from a 422 ErrorEnvelope, if present."""
        details = self.body.get("details")
        if not isinstance(details, dict):
            return None
        report = details.get("validation_report")
        return report if isinstance(report, dict) else None

    @property
    def is_compose_qa_failure(self) -> bool:
        return self.status_code == 422 and self.validation_report is not None


class CreativeAgentClient:
    """Thin wrapper over compose, enhance-retry, and TTS job endpoints."""

    def __init__(self, settings: OrchestratorSettings) -> None:
        self._settings = settings
        self._headers = {
            "X-API-Key": settings.api_key,
            "X-Tenant-Id": str(settings.tenant_id),
        }

    def _url(self, path: str) -> str:
        return f"{self._settings.api_base_url}{path}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        max_attempts = self._settings.api_request_retries + 1
        last_error: CreativeAgentApiError | None = None

        for attempt in range(max_attempts):
            if attempt > 0:
                backoff = self._settings.third_party_retry_backoff_seconds * attempt
                log_orchestrator_event(
                    f"retrying {method} {path} after transient error",
                    event_type="api_retry",
                    http_method=method,
                    path=path,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    backoff_seconds=backoff,
                    correlation_id=correlation_id,
                )
                time.sleep(backoff)

            log_orchestrator_event(
                f"{method} {path}",
                event_type="api_request",
                http_method=method,
                path=path,
                correlation_id=correlation_id,
            )
            try:
                with httpx.Client(timeout=httpx.Timeout(90.0, connect=15.0)) as client:
                    response = client.request(
                        method,
                        self._url(path),
                        headers=self._headers,
                        json=json_body,
                        params=params,
                    )
            except httpx.HTTPError as exc:
                last_error = CreativeAgentApiError(
                    f"{method} {path} failed (network): {exc}",
                )
                if attempt + 1 < max_attempts and is_transient_third_party_error(str(exc)):
                    continue
                raise last_error from exc

            if response.status_code >= 400:
                detail = response.text.strip() or response.reason_phrase
                body: dict[str, Any] = {}
                try:
                    parsed = response.json()
                    if isinstance(parsed, dict):
                        body = parsed
                except Exception:  # noqa: BLE001 — keep raw detail on non-JSON errors
                    body = {}
                last_error = CreativeAgentApiError(
                    f"{method} {path} failed ({response.status_code}): {detail}",
                    status_code=response.status_code,
                    body=body,
                )
                # Never treat compose QA (422 + validation_report) as a transient HTTP retry.
                if last_error.is_compose_qa_failure:
                    log_orchestrator_event(
                        f"{method} {path} compose QA failed",
                        level=logging.WARNING,
                        event_type="compose_qa_failed",
                        http_method=method,
                        path=path,
                        status_code=response.status_code,
                        correlation_id=correlation_id,
                        error_count=(last_error.validation_report or {}).get("error_count"),
                    )
                    raise last_error
                if (
                    attempt + 1 < max_attempts
                    and is_transient_third_party_error(detail, status_code=response.status_code)
                ):
                    log_orchestrator_event(
                        f"{method} {path} failed (will retry)",
                        level=logging.WARNING,
                        event_type="api_error",
                        http_method=method,
                        path=path,
                        status_code=response.status_code,
                        detail=detail,
                        correlation_id=correlation_id,
                    )
                    continue
                log_orchestrator_event(
                    f"{method} {path} failed",
                    level=logging.ERROR,
                    event_type="api_error",
                    http_method=method,
                    path=path,
                    status_code=response.status_code,
                    detail=detail,
                    correlation_id=correlation_id,
                )
                raise last_error

            log_orchestrator_event(
                f"{method} {path} ok",
                event_type="api_response",
                http_method=method,
                path=path,
                status_code=response.status_code,
                correlation_id=correlation_id,
            )
            if not response.content:
                return {}
            return response.json()

        assert last_error is not None
        raise last_error

    def compose_transcript(self, brief: dict[str, Any], *, correlation_id: str | None) -> dict[str, Any]:
        body = {**brief, "tenant_id": str(self._settings.tenant_id)}
        if correlation_id:
            body["correlation_id"] = correlation_id
        return self._request("POST", "/transcripts", json_body=body, correlation_id=correlation_id)

    def get_transcript(self, transcript_id: UUID, *, correlation_id: str | None = None) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/transcripts/{transcript_id}",
            correlation_id=correlation_id,
        )

    def retry_enhancement(
        self,
        transcript_id: UUID,
        *,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if correlation_id:
            body["correlation_id"] = correlation_id
        return self._request(
            "POST",
            f"/transcripts/{transcript_id}/retry-enhancement",
            json_body=body or None,
            correlation_id=correlation_id,
        )

    def list_versions(self, transcript_id: UUID, *, correlation_id: str | None = None) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/transcripts/{transcript_id}/versions",
            params={"include_content": "false"},
            correlation_id=correlation_id,
        )

    def create_audio_job(
        self,
        *,
        transcript_id: UUID,
        transcript_version_id: UUID,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "tenant_id": str(self._settings.tenant_id),
            "transcript_id": str(transcript_id),
            "transcript_version_id": str(transcript_version_id),
            "voice_profile_code": self._settings.voice_profile_code,
        }
        if correlation_id:
            body["correlation_id"] = correlation_id
        return self._request("POST", "/audio-jobs", json_body=body, correlation_id=correlation_id)

    def get_audio_job(self, audio_job_id: UUID, *, correlation_id: str | None = None) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/audio-jobs/{audio_job_id}",
            correlation_id=correlation_id,
        )

    def resolve_audio_job_last_error(
        self,
        audio_job_id: UUID,
        *,
        correlation_id: str | None = None,
        cached: str | None = None,
    ) -> str | None:
        """Read last_error from API, falling back to Aurora when the API omits it."""
        err = cached
        try:
            job = self.get_audio_job(audio_job_id, correlation_id=correlation_id)
            err = job.get("last_error") or err
        except CreativeAgentApiError:
            pass
        if err:
            return err
        return _audio_job_last_error_from_db(audio_job_id)

    def get_audio_manifest(self, audio_job_id: UUID, *, correlation_id: str | None = None) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/audio-jobs/{audio_job_id}/manifest",
            params={"include_urls": "true"},
            correlation_id=correlation_id,
        )

    def wait_for_transcript_status(
        self,
        transcript_id: UUID,
        *,
        target_statuses: set[str],
        failure_statuses: set[str],
        deadline: float,
        on_poll: Callable[[dict[str, Any]], None] | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        last_logged: str | None = None
        current: str | None = None
        while time.monotonic() < deadline:
            status = self.get_transcript(transcript_id, correlation_id=correlation_id)
            current = status.get("status")
            if on_poll:
                on_poll(status)
            if current != last_logged:
                log_orchestrator_event(
                    "polling transcript status",
                    event_type="poll_transcript",
                    transcript_id=str(transcript_id),
                    status=current,
                    correlation_id=correlation_id,
                )
                last_logged = current
            if current in target_statuses:
                return status
            if current in failure_statuses:
                return status
            time.sleep(self._settings.poll_seconds)
        raise TimeoutError(
            f"Timed out waiting for transcript {transcript_id}; last status={current}"
        )

    def wait_for_audio_job(
        self,
        audio_job_id: UUID,
        *,
        success_statuses: set[str],
        retryable_statuses: set[str],
        failure_statuses: set[str],
        deadline: float,
        on_poll: Callable[[dict[str, Any]], None] | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        last: dict[str, Any] | None = None
        last_logged: str | None = None
        while time.monotonic() < deadline:
            last = self.get_audio_job(audio_job_id, correlation_id=correlation_id)
            current = last.get("status")
            if on_poll:
                on_poll(last)
            if current != last_logged:
                log_orchestrator_event(
                    "polling audio job status",
                    event_type="poll_audio_job",
                    audio_job_id=str(audio_job_id),
                    status=current,
                    completed_chunks=last.get("completed_chunks"),
                    total_chunks=last.get("total_chunks"),
                    failed_chunks=last.get("failed_chunks"),
                    correlation_id=correlation_id,
                )
                last_logged = current
            if current in success_statuses | retryable_statuses | failure_statuses:
                return last
            time.sleep(self._settings.poll_seconds)
        raise TimeoutError(
            f"Timed out waiting for audio job {audio_job_id}; last status={last and last.get('status')}"
        )

    def download_final_mp3(
        self,
        audio_job_id: UUID,
        dest_path: str,
        *,
        correlation_id: str | None = None,
    ) -> str:
        log_orchestrator_event(
            "downloading final mp3",
            event_type="download_start",
            audio_job_id=str(audio_job_id),
            dest_path=dest_path,
            correlation_id=correlation_id,
        )
        manifest = self.get_audio_manifest(audio_job_id)
        final_url = manifest.get("final_url")
        if not final_url:
            raise CreativeAgentApiError(
                f"Manifest for audio job {audio_job_id} has no final_url",
            )
        max_attempts = self._settings.api_request_retries + 1
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            if attempt > 0:
                backoff = self._settings.third_party_retry_backoff_seconds * attempt
                log_orchestrator_event(
                    "retrying final mp3 download after transient error",
                    event_type="download_retry",
                    audio_job_id=str(audio_job_id),
                    attempt=attempt + 1,
                    backoff_seconds=backoff,
                    correlation_id=correlation_id,
                )
                time.sleep(backoff)
            try:
                with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
                    response = client.get(final_url)
                    response.raise_for_status()
                    path = Path(dest_path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(response.content)
                log_orchestrator_event(
                    "downloaded final mp3",
                    event_type="download_complete",
                    audio_job_id=str(audio_job_id),
                    dest_path=dest_path,
                    bytes_written=path.stat().st_size,
                    correlation_id=correlation_id,
                )
                return dest_path
            except (httpx.HTTPError, OSError) as exc:
                last_error = exc
                if attempt + 1 < max_attempts and is_transient_third_party_error(str(exc)):
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("download failed without error")


def _audio_job_last_error_from_db(audio_job_id: UUID) -> str | None:
    try:
        from db.repositories import AudioJobRepository
        from db.session import build_session_factory, session_scope

        factory = build_session_factory()
        with session_scope(factory) as session:
            job = AudioJobRepository(factory).get_audio_job(session, audio_job_id)
            if job is None:
                return None
            return job.last_error
    except Exception:
        return None
