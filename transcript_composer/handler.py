"""AWS Lambda entrypoint for Agent 1 — Pattern Transcript Composer."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from models.errors import ErrorCode, ErrorEnvelope
from models.requests import CreateTranscriptRequest
from transcript_composer.service import Agent1Service
from transcript_composer.validation import TranscriptValidationError


def parse_event(event: dict[str, Any]) -> CreateTranscriptRequest:
    """Accept API Gateway proxy events or direct invocation payloads."""
    payload: dict[str, Any]
    if "body" in event:
        body = event["body"]
        payload = json.loads(body) if isinstance(body, str) else body
    else:
        payload = event
    return CreateTranscriptRequest.model_validate(payload)


def success_response(result_body: dict[str, Any], *, status_code: int = 200) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(result_body),
    }


def error_response(envelope: ErrorEnvelope, *, status_code: int = 400) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": envelope.model_dump_json(),
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda 1 handler: validate brief → compose → persist → publish SQS."""
    correlation_id = event.get("correlation_id") or event.get("headers", {}).get("x-correlation-id")
    try:
        request = parse_event(event)
        if correlation_id and not request.correlation_id:
            request = request.model_copy(update={"correlation_id": str(correlation_id)})
    except (ValidationError, json.JSONDecodeError, TypeError) as exc:
        envelope = ErrorEnvelope(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Invalid transcript request",
            details={"error": str(exc)},
            correlation_id=str(correlation_id) if correlation_id else None,
        )
        return error_response(envelope, status_code=400)

    try:
        result = Agent1Service().run(request)
    except TranscriptValidationError as exc:
        envelope = ErrorEnvelope(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Generated transcript failed pattern validation",
            details={
                "error": str(exc),
                "validation_report": exc.report.model_dump(mode="json"),
            },
            correlation_id=request.correlation_id,
        )
        return error_response(envelope, status_code=422)
    except Exception as exc:
        envelope = ErrorEnvelope(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Agent 1 composition failed",
            details={"error": str(exc)},
            correlation_id=request.correlation_id,
        )
        return error_response(envelope, status_code=500)

    body = {
        "transcript_id": str(result.output.transcript_id),
        "version_id": str(result.output.version_id),
        "title": result.output.title,
        "status": result.output.status.value,
        "duration_estimate_seconds": result.output.duration_estimate.seconds,
        "queue_message_id": result.queue_message_id,
        "pattern_plan": result.output.pattern_plan.model_dump(mode="json"),
    }
    return success_response(body, status_code=201)
