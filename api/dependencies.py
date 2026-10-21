"""FastAPI dependency injection."""

from __future__ import annotations

from db.repositories import AudioJobRepository, TranscriptRepository
from db.session import build_session_factory
from transcript_composer.service import Agent1Service
from api.transcript_service import TranscriptApiService
from api.audio_service import AudioJobApiService


def get_transcript_repository() -> TranscriptRepository:
    return TranscriptRepository(build_session_factory())


def get_agent1_service() -> Agent1Service:
    return Agent1Service()


def get_transcript_api_service() -> TranscriptApiService:
    return TranscriptApiService(repository=get_transcript_repository())


def get_audio_job_repository() -> AudioJobRepository:
    return AudioJobRepository(build_session_factory())


def get_audio_job_api_service() -> AudioJobApiService:
    return AudioJobApiService(repository=get_audio_job_repository())
