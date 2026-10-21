"""TTS audio job API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status

from api.auth import assert_tenant_access, require_api_key, require_tenant_header
from api.dependencies import get_audio_job_api_service
from api.audio_service import AudioJobApiService
from db.exceptions import AudioJobNotFoundError
from models.errors import ErrorCode, ErrorEnvelope
from models.requests import CreateAudioJobApiRequest
from models.responses import AudioJobManifestResponse, AudioJobStatusResponse, CreateAudioJobResponse

router = APIRouter(prefix="/audio-jobs", tags=["audio-jobs"])


def _correlation_id(request: Request, header_value: str | None) -> str | None:
    return header_value or request.headers.get("x-correlation-id")


@router.post(
    "",
    response_model=CreateAudioJobResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
def create_audio_job(
    body: CreateAudioJobApiRequest,
    request: Request,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
    service: AudioJobApiService = Depends(get_audio_job_api_service),
) -> CreateAudioJobResponse:
    if x_tenant_id is not None:
        assert_tenant_access(
            resource_tenant_id=body.tenant_id,
            caller_tenant_id=UUID(x_tenant_id),
        )

    correlation_id = _correlation_id(request, x_correlation_id)
    if correlation_id and not body.correlation_id:
        body = body.model_copy(update={"correlation_id": correlation_id})

    try:
        return service.create_audio_job(body)
    except ValueError as exc:
        raise _validation_error(str(exc)) from exc


@router.get(
    "/{audio_job_id}",
    response_model=AudioJobStatusResponse,
    dependencies=[Depends(require_api_key)],
)
def get_audio_job(
    audio_job_id: UUID,
    tenant_id: UUID = Depends(require_tenant_header),
    service: AudioJobApiService = Depends(get_audio_job_api_service),
) -> AudioJobStatusResponse:
    try:
        return service.get_audio_job_status(audio_job_id, tenant_id=tenant_id)
    except AudioJobNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except PermissionError as exc:
        raise _forbidden(str(exc)) from exc


@router.get(
    "/{audio_job_id}/manifest",
    response_model=AudioJobManifestResponse,
    dependencies=[Depends(require_api_key)],
)
def get_audio_job_manifest(
    audio_job_id: UUID,
    tenant_id: UUID = Depends(require_tenant_header),
    include_urls: bool = Query(default=False),
    url_expires_in: int = Query(default=3600, ge=60, le=86400),
    service: AudioJobApiService = Depends(get_audio_job_api_service),
) -> AudioJobManifestResponse:
    try:
        return service.get_audio_job_manifest(
            audio_job_id,
            tenant_id=tenant_id,
            include_urls=include_urls,
            url_expires_in=url_expires_in,
        )
    except AudioJobNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except PermissionError as exc:
        raise _forbidden(str(exc)) from exc
    except ValueError as exc:
        raise _state_error(str(exc)) from exc


def _not_found(message: str):
    from fastapi import HTTPException

    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ErrorEnvelope(error_code=ErrorCode.NOT_FOUND, message=message).model_dump(
            mode="json"
        ),
    )


def _forbidden(message: str):
    from fastapi import HTTPException

    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=ErrorEnvelope(error_code=ErrorCode.VALIDATION_ERROR, message=message).model_dump(
            mode="json"
        ),
    )


def _state_error(message: str):
    from fastapi import HTTPException

    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=ErrorEnvelope(
            error_code=ErrorCode.CONFLICT,
            message=message,
        ).model_dump(mode="json"),
    )


def _validation_error(message: str):
    from fastapi import HTTPException

    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ErrorEnvelope(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=message,
        ).model_dump(mode="json"),
    )
