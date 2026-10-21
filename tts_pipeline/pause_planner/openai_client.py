"""Thin OpenAI client for meditation pause planning (raw JSON, pre-normalize)."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable

from transcript_composer.llm_config import (
    ensure_dotenv_loaded,
    require_openai_api_key,
)

from tts_pipeline.pause_planner.errors import (
    PausePlannerError,
    PausePlannerTransientError,
    PausePlannerValidationError,
)
from tts_pipeline.pause_planner.prompt import build_system_prompt, build_user_prompt

logger = logging.getLogger("creative_agent.tts.pause_planner")

DEFAULT_PAUSE_PLANNER_MODEL = "gpt-4o-mini"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_TIMEOUT_SECONDS = 45.0
DEFAULT_MAX_ATTEMPTS = 3

CreateCompletionFn = Callable[..., Any]


def resolve_pause_planner_model() -> str:
    ensure_dotenv_loaded()
    return (
        os.environ.get("CREATIVE_AGENT_PAUSE_PLANNER_MODEL", "").strip()
        or os.environ.get("CREATIVE_AGENT_OPENAI_MODEL", "").strip()
        or DEFAULT_PAUSE_PLANNER_MODEL
    )


class OpenAIPausePlannerClient:
    """Call OpenAI chat completions and return a parsed JSON object."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        model: str | None = None,
        api_key: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        create_completion: CreateCompletionFn | None = None,
    ) -> None:
        if temperature > 0.3:
            raise PausePlannerError("pause planner temperature must be <= 0.3")
        if max_attempts < 1:
            raise PausePlannerError("max_attempts must be >= 1")

        ensure_dotenv_loaded()
        self._model = model or resolve_pause_planner_model()
        self._temperature = temperature
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self.last_latency_ms: float | None = None

        if create_completion is not None:
            self._create_completion = create_completion
            self._client = client
        else:
            self._client = client or self._build_client(api_key or require_openai_api_key())
            self._create_completion = self._client.chat.completions.create

    @property
    def model(self) -> str:
        return self._model

    def plan_pauses(
        self,
        *,
        beats: list[str],
        paragraphs: list[str],
        target_duration_seconds: int,
        estimated_speech_seconds: int,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
    ) -> dict[str, Any]:
        """Return raw planner JSON (typically ``{"holds": [...]}``).

        Does **not** normalize or clamp — callers run ``normalize_pause_plan``.
        """
        if target_duration_seconds < 1:
            raise PausePlannerValidationError("target_duration_seconds must be >= 1")
        if estimated_speech_seconds < 0:
            raise PausePlannerValidationError("estimated_speech_seconds must be >= 0")
        if not beats and not paragraphs:
            raise PausePlannerValidationError("beats or paragraphs are required")

        system = system_prompt or build_system_prompt()
        user = user_prompt or build_user_prompt(
            beats=beats,
            paragraphs=paragraphs,
            target_duration_seconds=target_duration_seconds,
            estimated_speech_seconds=estimated_speech_seconds,
        )

        content = self._complete_json(system=system, user=user)
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise PausePlannerValidationError(
                f"pause planner returned non-JSON content: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise PausePlannerValidationError("pause planner JSON root must be an object")
        return payload

    def _complete_json(self, *, system: str, user: str) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            started = time.perf_counter()
            try:
                response = self._create_completion(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=self._temperature,
                    response_format={"type": "json_object"},
                    timeout=self._timeout_seconds,
                )
                self.last_latency_ms = (time.perf_counter() - started) * 1000.0
                content = _message_content(response)
                if not content or not str(content).strip():
                    raise PausePlannerValidationError("OpenAI returned empty pause plan")
                logger.info(
                    "pause planner completion ok attempt=%s latency_ms=%.1f model=%s",
                    attempt,
                    self.last_latency_ms,
                    self._model,
                )
                return str(content)
            except PausePlannerValidationError:
                self.last_latency_ms = (time.perf_counter() - started) * 1000.0
                raise
            except Exception as exc:  # noqa: BLE001 — classify then re-raise
                self.last_latency_ms = (time.perf_counter() - started) * 1000.0
                last_error = exc
                if not _is_transient(exc) or attempt >= self._max_attempts:
                    if _is_transient(exc):
                        raise PausePlannerTransientError(
                            f"pause planner failed after {attempt} attempts: {_redact(str(exc))}"
                        ) from exc
                    raise PausePlannerError(
                        f"pause planner request failed: {_redact(str(exc))}"
                    ) from exc
                backoff = min(2.0 ** (attempt - 1), 8.0)
                logger.warning(
                    "pause planner transient error attempt=%s/%s backoff=%.1fs err=%s",
                    attempt,
                    self._max_attempts,
                    backoff,
                    _redact(str(exc)),
                )
                time.sleep(backoff)

        raise PausePlannerTransientError(
            f"pause planner failed after {self._max_attempts} attempts: "
            f"{_redact(str(last_error))}"
        )

    @staticmethod
    def _build_client(api_key: str) -> Any:
        from openai import OpenAI

        return OpenAI(api_key=api_key)


def _message_content(response: Any) -> str | None:
    try:
        return response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise PausePlannerValidationError(
            "unexpected OpenAI response shape for pause planner"
        ) from exc


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    name = type(exc).__name__.lower()
    if "timeout" in name or "rate" in name or "apiconnection" in name:
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status in {408, 429, 500, 502, 503, 504}:
        return True
    text = str(exc).lower()
    return any(
        token in text
        for token in ("timeout", "rate limit", "temporar", "503", "502", "429", "connection")
    )


def _redact(text: str) -> str:
    """Avoid leaking secrets if an exception message echoes headers/keys."""
    lowered = text
    for marker in ("Bearer ", "api_key", "Authorization"):
        if marker.lower() in lowered.lower():
            return "<redacted error containing credential-like text>"
    if len(text) > 400:
        return text[:400] + "…"
    return text
