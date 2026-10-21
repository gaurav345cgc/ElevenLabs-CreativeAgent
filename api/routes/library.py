"""Listen library API — browse completed meditations by taxonomy."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from api.auth import require_api_key, require_tenant_header
from api.dependencies import get_audio_job_repository, get_transcript_repository
from api.library_service import LibraryApiService
from db.repositories import AudioJobRepository, TranscriptRepository
from models.requests import RetainLibraryRequest
from models.responses import LibraryResponse, RetainLibraryResponse

router = APIRouter(prefix="/library", tags=["library"])


def get_library_api_service(
    transcript_repository: TranscriptRepository = Depends(get_transcript_repository),
    audio_repository: AudioJobRepository = Depends(get_audio_job_repository),
) -> LibraryApiService:
    return LibraryApiService(
        transcript_repository=transcript_repository,
        audio_repository=audio_repository,
    )


@router.get(
    "",
    response_model=LibraryResponse,
    dependencies=[Depends(require_api_key)],
)
def list_library(
    tenant_id: UUID = Depends(require_tenant_header),
    service: LibraryApiService = Depends(get_library_api_service),
) -> LibraryResponse:
    """Completed audio jobs for this tenant, with pillar / generation / wound labels."""
    return service.list_library(tenant_id=tenant_id)


@router.post(
    "/retain",
    response_model=RetainLibraryResponse,
    dependencies=[Depends(require_api_key)],
)
def retain_library(
    body: RetainLibraryRequest,
    tenant_id: UUID = Depends(require_tenant_header),
    service: LibraryApiService = Depends(get_library_api_service),
) -> RetainLibraryResponse:
    """Keep only the given transcripts in the library; archive other completed audio jobs."""
    return service.retain_library(tenant_id=tenant_id, request=body)
