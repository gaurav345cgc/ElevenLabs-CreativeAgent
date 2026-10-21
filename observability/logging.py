"""Structured logging for persistence and agent operations."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

logger = logging.getLogger("creative_agent.persistence")
composer_logger = logging.getLogger("creative_agent.composer")
enhancer_logger = logging.getLogger("creative_agent.enhancer")
orchestrator_logger = logging.getLogger("creative_agent.orchestrator")
api_logger = logging.getLogger("creative_agent.api")
queue_logger = logging.getLogger("creative_agent.queue")

CREATIVE_AGENT_LOGGERS = (
    logger,
    composer_logger,
    enhancer_logger,
    orchestrator_logger,
    api_logger,
    queue_logger,
)


def _json_default(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def _emit(
    log: logging.Logger,
    message: str,
    *,
    level: int = logging.INFO,
    service: str,
    environment: str | None = None,
    correlation_id: str | None = None,
    event_type: str | None = None,
    **context: Any,
) -> None:
    payload: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": logging.getLevelName(level),
        "message": message,
        "service": service,
        "environment": environment or os.environ.get("CREATIVE_AGENT_ENVIRONMENT"),
        "correlation_id": correlation_id,
        **context,
    }
    if event_type is not None:
        payload["event_type"] = event_type
    log.log(level, json.dumps(payload, default=_json_default))


_orchestrator_plain_logs = False


def configure_service_logger(
    log: logging.Logger,
    *,
    level: int | None = None,
    human_readable: bool = False,
) -> None:
    """Attach a stderr handler once per service logger."""
    if log.handlers:
        return
    resolved_level = level
    if resolved_level is None:
        env_level = os.environ.get("CREATIVE_AGENT_LOG_LEVEL", "INFO").upper()
        resolved_level = getattr(logging, env_level, logging.INFO)

    handler = logging.StreamHandler()
    if human_readable:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
    else:
        handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
    log.setLevel(resolved_level)
    log.propagate = False


def configure_orchestrator_logging(
    *,
    level: int | None = None,
    human_readable: bool = True,
) -> None:
    global _orchestrator_plain_logs
    _orchestrator_plain_logs = human_readable
    if orchestrator_logger.handlers:
        return
    configure_service_logger(
        orchestrator_logger,
        level=level,
        human_readable=human_readable,
    )


def configure_api_logging(*, level: int | None = None) -> None:
    configure_service_logger(api_logger, level=level, human_readable=False)


def configure_queue_logging(*, level: int | None = None) -> None:
    configure_service_logger(queue_logger, level=level, human_readable=False)


def configure_all_logging(*, orchestrator_human_readable: bool = False) -> None:
    """Configure all first-party service loggers (call at process entry)."""
    from observability.tts import configure_tts_logging

    configure_tts_logging()
    configure_api_logging()
    configure_queue_logging()
    configure_service_logger(logger, human_readable=False)
    configure_service_logger(composer_logger, human_readable=False)
    configure_service_logger(enhancer_logger, human_readable=False)
    configure_orchestrator_logging(human_readable=orchestrator_human_readable)


def log_db_event(
    message: str,
    *,
    level: int = logging.INFO,
    service: str = "persistence",
    environment: str | None = None,
    correlation_id: str | None = None,
    event_type: str | None = None,
    **context: Any,
) -> None:
    _emit(
        logger,
        message,
        level=level,
        service=service,
        environment=environment,
        correlation_id=correlation_id,
        event_type=event_type,
        **context,
    )


def log_composer_event(
    message: str,
    *,
    level: int = logging.INFO,
    environment: str | None = None,
    correlation_id: str | None = None,
    event_type: str | None = None,
    **context: Any,
) -> None:
    _emit(
        composer_logger,
        message,
        level=level,
        service="composer",
        environment=environment,
        correlation_id=correlation_id,
        event_type=event_type,
        **context,
    )


def log_enhancer_event(
    message: str,
    *,
    level: int = logging.INFO,
    environment: str | None = None,
    correlation_id: str | None = None,
    event_type: str | None = None,
    **context: Any,
) -> None:
    _emit(
        enhancer_logger,
        message,
        level=level,
        service="enhancer",
        environment=environment,
        correlation_id=correlation_id,
        event_type=event_type,
        **context,
    )


def log_orchestrator_event(
    message: str,
    *,
    level: int = logging.INFO,
    environment: str | None = None,
    correlation_id: str | None = None,
    event_type: str | None = None,
    **context: Any,
) -> None:
    if _orchestrator_plain_logs:
        fields = dict(context)
        if correlation_id is not None:
            fields["correlation_id"] = correlation_id
        if event_type is not None:
            fields["event_type"] = event_type
        extra = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
        line = f"{message} {extra}".strip()
        orchestrator_logger.log(level, line)
        return
    _emit(
        orchestrator_logger,
        message,
        level=level,
        service="orchestrator",
        environment=environment,
        correlation_id=correlation_id,
        event_type=event_type,
        **context,
    )


def log_api_event(
    message: str,
    *,
    level: int = logging.INFO,
    environment: str | None = None,
    correlation_id: str | None = None,
    event_type: str | None = None,
    **context: Any,
) -> None:
    _emit(
        api_logger,
        message,
        level=level,
        service="api",
        environment=environment,
        correlation_id=correlation_id,
        event_type=event_type,
        **context,
    )


def log_queue_event(
    message: str,
    *,
    level: int = logging.INFO,
    environment: str | None = None,
    correlation_id: str | None = None,
    event_type: str | None = None,
    queue_name: str | None = None,
    **context: Any,
) -> None:
    _emit(
        queue_logger,
        message,
        level=level,
        service="queue",
        environment=environment,
        correlation_id=correlation_id,
        event_type=event_type,
        queue_name=queue_name,
        **context,
    )
