"""FastAPI application factory and exception handlers."""

from __future__ import annotations

import json
import os
import socket

import pathlib
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import ValidationError

from api.routes.transcripts import router as transcripts_router
from api.routes.audio_jobs import router as audio_jobs_router
from api.routes.library import router as library_router
from api.production_state import load_production_state, save_production_state
from api.auth import require_api_key
from db.engine import create_db_engine
from models.errors import ErrorCode, ErrorEnvelope
from models.responses import BackgroundProfileItem, BackgroundProfilesResponse
from tts_pipeline.background_policy import DEFAULT_BACKGROUND_PROFILE_CODE, catalog_entries
from transcript_composer.llm_config import ensure_dotenv_loaded
from transcript_composer.validation import TranscriptValidationError
from observability.logging import configure_all_logging

ensure_dotenv_loaded()
configure_all_logging()

_API_DIR = pathlib.Path(__file__).parent
_TEMPLATES_DIR = _API_DIR / "templates"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Creative Agent Intake API",
        version="1.0.0",
        description="Internal API for transcript composition, enhancement, and TTS audio jobs",
    )
    app.include_router(transcripts_router)
    app.include_router(audio_jobs_router)
    app.include_router(library_router)

    @app.get(
        "/background-profiles",
        response_model=BackgroundProfilesResponse,
        tags=["audio-jobs"],
        dependencies=[Depends(require_api_key)],
    )
    def list_background_profiles() -> BackgroundProfilesResponse:
        from api.transcript_service import _preview_url_for_key

        profiles = []
        for entry in catalog_entries():
            profiles.append(
                BackgroundProfileItem(
                    code=entry["code"],
                    display_name=entry["display_name"],
                    mood=entry["mood"],
                    track_object_key=entry["track_object_key"],
                    preview_url=_preview_url_for_key(entry["track_object_key"]),
                )
            )
        return BackgroundProfilesResponse(
            default_code=DEFAULT_BACKGROUND_PROFILE_CODE,
            profiles=profiles,
        )

    @app.get("/dashboard", response_class=HTMLResponse, tags=["dashboard"])
    def get_dashboard() -> HTMLResponse:
        path = _TEMPLATES_DIR / "dashboard.html"
        return HTMLResponse(content=path.read_text(encoding="utf-8"))

    @app.get("/dashboard/production", response_class=HTMLResponse, tags=["dashboard"])
    def get_production_dashboard() -> HTMLResponse:
        """CEO / leadership view of First-10 thin-wound production progress."""
        path = _TEMPLATES_DIR / "production.html"
        return HTMLResponse(content=path.read_text(encoding="utf-8"))

    @app.get("/dashboard/library", response_class=HTMLResponse, tags=["dashboard"])
    def get_library_dashboard() -> HTMLResponse:
        """Browse completed meditations by pillar / generation / wound."""
        path = _TEMPLATES_DIR / "library.html"
        return HTMLResponse(content=path.read_text(encoding="utf-8"))

    @app.get("/dashboard/production/state", tags=["dashboard"])
    def get_production_state() -> dict:
        return load_production_state()

    @app.put("/dashboard/production/state", tags=["dashboard"])
    def put_production_state(payload: dict) -> dict:
        payload = dict(payload)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        return save_production_state(payload)

    @app.exception_handler(TranscriptValidationError)
    async def transcript_validation_handler(
        request: Request,
        exc: TranscriptValidationError,
    ) -> JSONResponse:
        correlation_id = request.headers.get("x-correlation-id")
        envelope = ErrorEnvelope(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Generated transcript failed pattern validation",
            details={
                "error": str(exc),
                "validation_report": exc.report.model_dump(mode="json"),
            },
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=envelope.model_dump(mode="json"),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        correlation_id = request.headers.get("x-correlation-id")
        # FastAPI may put exception objects in error ctx (e.g. TaxonomyValidationError);
        # those are not JSON-serializable and used to crash into a bare 500.
        safe_errors = json.loads(json.dumps(exc.errors(), default=str))
        envelope = ErrorEnvelope(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Request validation failed",
            details={"errors": safe_errors},
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=envelope.model_dump(mode="json"),
        )

    @app.exception_handler(ValidationError)
    async def pydantic_validation_handler(
        request: Request,
        exc: ValidationError,
    ) -> JSONResponse:
        correlation_id = request.headers.get("x-correlation-id")
        envelope = ErrorEnvelope(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Validation failed",
            details={"errors": exc.errors()},
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=envelope.model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        """Return JSON details instead of opaque API Gateway 'Internal Server Error'."""
        import logging

        correlation_id = request.headers.get("x-correlation-id")
        logging.getLogger("creative_agent.api").exception(
            "unhandled API error path=%s", request.url.path
        )
        envelope = ErrorEnvelope(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Internal server error during request",
            details={
                "error_type": type(exc).__name__,
                "error": str(exc)[:2000],
                "path": request.url.path,
            },
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=envelope.model_dump(mode="json"),
        )

    @app.get("/health", tags=["health"])
    def health(deep: bool = Query(default=False)) -> dict[str, object]:
        if not deep:
            return {"status": "ok"}

        result: dict[str, object] = {"status": "ok", "checks": {}}
        checks: dict[str, object] = result["checks"]  # type: ignore[assignment]

        # DB connectivity (fast-fail via connect_timeout in db.engine).
        try:
            engine = create_db_engine(echo=False)
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            checks["db"] = {"ok": True}
        except Exception as exc:
            checks["db"] = {"ok": False, "error": str(exc)}

        # DNS + outbound HTTPS sanity (helps diagnose VPC/NAT issues).
        try:
            ip = socket.gethostbyname("api.openai.com")
            checks["openai_dns"] = {"ok": True, "ip": ip}
        except Exception as exc:
            checks["openai_dns"] = {"ok": False, "error": str(exc)}

        try:
            import httpx

            timeout_s = float(os.environ.get("CREATIVE_AGENT_HEALTHCHECK_HTTP_TIMEOUT", "2.5"))
            with httpx.Client(timeout=timeout_s) as client:
                r = client.get("https://api.openai.com/")
            checks["openai_https"] = {"ok": r.status_code < 500, "status_code": r.status_code}
        except Exception as exc:
            checks["openai_https"] = {"ok": False, "error": str(exc)}

        # Auth check against the key the Lambda actually uses (env or Secrets Manager).
        try:
            from transcript_composer.llm_config import resolve_openai_api_key

            key = resolve_openai_api_key()
            if not key:
                checks["openai_auth"] = {"ok": False, "error": "no OpenAI API key configured"}
            else:
                from openai import OpenAI

                OpenAI(api_key=key).models.list()
                checks["openai_auth"] = {"ok": True}
        except Exception as exc:
            checks["openai_auth"] = {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            }

        return result

    return app


app = create_app()
