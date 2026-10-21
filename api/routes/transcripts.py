"""Transcript intake API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from api.auth import assert_tenant_access, require_api_key, require_tenant_header
from api.dependencies import get_agent1_service, get_transcript_api_service
from api.transcript_service import TranscriptApiService
from db.exceptions import TranscriptNotFoundError
from models.errors import ErrorCode, ErrorEnvelope
from models.enums import TranscriptStatus
from models.requests import (
    CreateTranscriptRequest,
    RetryEnhancementRequest,
    ApproveTranscriptRequest,
    SetBackgroundProfileRequest,
)
from models.responses import (
    CreateTranscriptResponse,
    RetryEnhancementResponse,
    TranscriptStatusResponse,
    TranscriptVersionsResponse,
    TranscriptWaitResponse,
    ClearPendingReviewResponse,
)
from transcript_composer.service import Agent1Service

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


def _correlation_id(request: Request, header_value: str | None) -> str | None:
    return header_value or request.headers.get("x-correlation-id")


@router.post(
    "",
    response_model=CreateTranscriptResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
def create_transcript(
    body: CreateTranscriptRequest,
    request: Request,
    agent1: Agent1Service = Depends(get_agent1_service),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
) -> CreateTranscriptResponse:
    if x_tenant_id is not None:
        assert_tenant_access(
            resource_tenant_id=body.tenant_id,
            caller_tenant_id=UUID(x_tenant_id),
        )

    correlation_id = _correlation_id(request, x_correlation_id)
    if correlation_id and not body.correlation_id:
        body = body.model_copy(update={"correlation_id": correlation_id})

    result = agent1.run(body)
    return CreateTranscriptResponse(
        transcript_id=result.output.transcript_id,
        version_id=result.output.version_id,
        title=result.output.title,
        status=result.output.status,
        duration_estimate_seconds=result.output.duration_estimate.seconds,
        queue_message_id=result.queue_message_id,
        pattern_plan=result.output.pattern_plan,
        correlation_id=body.correlation_id,
    )


@router.get(
    "/{transcript_id}",
    response_model=TranscriptStatusResponse,
    dependencies=[Depends(require_api_key)],
)
def get_transcript(
    transcript_id: UUID,
    tenant_id: UUID = Depends(require_tenant_header),
    service: TranscriptApiService = Depends(get_transcript_api_service),
) -> TranscriptStatusResponse:
    try:
        return service.get_transcript_status(transcript_id, tenant_id=tenant_id)
    except TranscriptNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except PermissionError as exc:
        raise _forbidden(str(exc)) from exc


@router.get(
    "/{transcript_id}/wait",
    response_model=TranscriptWaitResponse,
    dependencies=[Depends(require_api_key)],
)
def wait_for_enhanced_transcript(
    transcript_id: UUID,
    response: Response,
    tenant_id: UUID = Depends(require_tenant_header),
    include_content: bool = Query(default=True),
    max_wait_seconds: int = Query(default=25, ge=1, le=25),
    service: TranscriptApiService = Depends(get_transcript_api_service),
) -> TranscriptWaitResponse:
    """Block until Agent 2 finishes (or until max_wait_seconds). Call after create/compose."""
    try:
        body, finished = service.wait_for_enhanced_transcript(
            transcript_id,
            tenant_id=tenant_id,
            max_wait_seconds=max_wait_seconds,
            include_content=include_content,
        )
    except TranscriptNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except PermissionError as exc:
        raise _forbidden(str(exc)) from exc

    if body.ready:
        return body
    if finished and body.status in {
        TranscriptStatus.FAILED_ENHANCEMENT,
        TranscriptStatus.REVIEW_REQUIRED,
    }:
        response.status_code = status.HTTP_409_CONFLICT
        return body

    response.status_code = status.HTTP_202_ACCEPTED
    return body


@router.get(
    "/{transcript_id}/versions",
    response_model=TranscriptVersionsResponse,
    dependencies=[Depends(require_api_key)],
)
def get_transcript_versions(
    transcript_id: UUID,
    tenant_id: UUID = Depends(require_tenant_header),
    include_content: bool = Query(default=False),
    service: TranscriptApiService = Depends(get_transcript_api_service),
) -> TranscriptVersionsResponse:
    try:
        return service.list_versions(
            transcript_id,
            tenant_id=tenant_id,
            include_content=include_content,
        )
    except TranscriptNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except PermissionError as exc:
        raise _forbidden(str(exc)) from exc


@router.post(
    "/{transcript_id}/retry-enhancement",
    response_model=RetryEnhancementResponse,
    dependencies=[Depends(require_api_key)],
)
def retry_enhancement(
    transcript_id: UUID,
    tenant_id: UUID = Depends(require_tenant_header),
    body: RetryEnhancementRequest | None = None,
    service: TranscriptApiService = Depends(get_transcript_api_service),
) -> RetryEnhancementResponse:
    try:
        return service.retry_enhancement(
            transcript_id,
            tenant_id=tenant_id,
            body=body,
        )
    except TranscriptNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except PermissionError as exc:
        raise _forbidden(str(exc)) from exc
    except ValueError as exc:
        raise _state_error(str(exc)) from exc


@router.put(
    "/{transcript_id}/background",
    response_model=TranscriptVersionsResponse,
    dependencies=[Depends(require_api_key)],
)
def set_transcript_background(
    transcript_id: UUID,
    body: SetBackgroundProfileRequest,
    tenant_id: UUID = Depends(require_tenant_header),
    service: TranscriptApiService = Depends(get_transcript_api_service),
) -> TranscriptVersionsResponse:
    try:
        return service.set_background_profile(
            transcript_id,
            tenant_id=tenant_id,
            profile_code=body.profile_code,
        )
    except TranscriptNotFoundError as exc:
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
            error_code=ErrorCode.TRANSCRIPT_STATE_ERROR,
            message=message,
        ).model_dump(mode="json"),
    )


@router.get(
    "",
    response_model=list[TranscriptStatusResponse],
    dependencies=[Depends(require_api_key)],
)
def list_transcripts(
    status: TranscriptStatus | None = Query(default=None),
    tenant_id: UUID = Depends(require_tenant_header),
    service: TranscriptApiService = Depends(get_transcript_api_service),
) -> list[TranscriptStatusResponse]:
    return service.list_transcripts(tenant_id=tenant_id, status=status)


@router.post(
    "/clear-pending-review",
    response_model=ClearPendingReviewResponse,
    dependencies=[Depends(require_api_key)],
)
def clear_pending_review(
    tenant_id: UUID = Depends(require_tenant_header),
    service: TranscriptApiService = Depends(get_transcript_api_service),
) -> ClearPendingReviewResponse:
    """Remove all ENHANCED scripts from the Script Hub approval queue."""
    return service.clear_pending_review(tenant_id=tenant_id)


@router.post(
    "/{transcript_id}/approve",
    response_model=TranscriptStatusResponse,
    dependencies=[Depends(require_api_key)],
)
def approve_transcript(
    transcript_id: UUID,
    body: ApproveTranscriptRequest | None = None,
    tenant_id: UUID = Depends(require_tenant_header),
    service: TranscriptApiService = Depends(get_transcript_api_service),
) -> TranscriptStatusResponse:
    body = body or ApproveTranscriptRequest()
    try:
        return service.approve_transcript(
            transcript_id,
            tenant_id=tenant_id,
            approved_text=body.approved_text,
            background_profile_code=body.background_profile_code,
            correlation_id=body.correlation_id,
        )
    except TranscriptNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except PermissionError as exc:
        raise _forbidden(str(exc)) from exc
    except ValueError as exc:
        raise _state_error(str(exc)) from exc
