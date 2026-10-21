"""Controlled ElevenLabs Create speech client for TTS chunk synthesis."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from tts_pipeline.generator.config import (
    DEFAULT_APPLY_TEXT_NORMALIZATION,
    DEFAULT_ENABLE_LOGGING,
    DEFAULT_MIME_TYPE,
    DEFAULT_MODEL_ID,
    DEFAULT_OUTPUT_FORMAT,
    ELEVENLABS_API_BASE_URL,
    require_elevenlabs_api_key,
)


class VoiceSettings(BaseModel):
    stability: float | None = None
    similarity_boost: float | None = None
    style: float | None = None
    use_speaker_boost: bool | None = None
    speed: float | None = None


class PronunciationDictionaryLocator(BaseModel):
    pronunciation_dictionary_id: str
    version_id: str


class SpeechSynthesisRequest(BaseModel):
    text: str = Field(min_length=1)
    voice_id: str = Field(min_length=1)
    model_id: str = DEFAULT_MODEL_ID
    output_format: str = DEFAULT_OUTPUT_FORMAT
    voice_settings: VoiceSettings | None = None
    seed: int | None = None
    apply_text_normalization: str = DEFAULT_APPLY_TEXT_NORMALIZATION
    enable_logging: bool = DEFAULT_ENABLE_LOGGING
    pronunciation_dictionary_locators: list[PronunciationDictionaryLocator] | None = None
    previous_text: str | None = None
    next_text: str | None = None
    previous_request_ids: list[str] | None = None
    next_request_ids: list[str] | None = None

    def to_api_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "text": self.text,
            "model_id": self.model_id,
            "apply_text_normalization": self.apply_text_normalization,
            "enable_logging": self.enable_logging,
        }
        if self.voice_settings is not None:
            body["voice_settings"] = self.voice_settings.model_dump(exclude_none=True)
        if self.seed is not None:
            body["seed"] = self.seed
        if self.pronunciation_dictionary_locators:
            body["pronunciation_dictionary_locators"] = [
                item.model_dump() for item in self.pronunciation_dictionary_locators
            ]
        if self.previous_text is not None:
            body["previous_text"] = self.previous_text
        if self.next_text is not None:
            body["next_text"] = self.next_text
        if self.previous_request_ids:
            body["previous_request_ids"] = self.previous_request_ids
        if self.next_request_ids:
            body["next_request_ids"] = self.next_request_ids
        return body


class SpeechSynthesisResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    audio_bytes: bytes
    request_id: str | None = None
    response_headers: dict[str, str] = Field(default_factory=dict)
    byte_size: int
    checksum_sha256: str
    mime_type: str = DEFAULT_MIME_TYPE
    output_format: str = DEFAULT_OUTPUT_FORMAT

    @classmethod
    def from_audio(
        cls,
        audio_bytes: bytes,
        *,
        response_headers: dict[str, str],
        output_format: str = DEFAULT_OUTPUT_FORMAT,
        mime_type: str = DEFAULT_MIME_TYPE,
    ) -> SpeechSynthesisResult:
        normalized_headers = {key.lower(): value for key, value in response_headers.items()}
        return cls(
            audio_bytes=audio_bytes,
            request_id=normalized_headers.get("request-id"),
            response_headers=normalized_headers,
            byte_size=len(audio_bytes),
            checksum_sha256=hashlib.sha256(audio_bytes).hexdigest(),
            mime_type=mime_type,
            output_format=output_format,
        )


class ElevenLabsTransport(Protocol):
    def create_speech(
        self,
        *,
        voice_id: str,
        output_format: str,
        body: dict[str, Any],
    ) -> tuple[bytes, dict[str, str]]: ...


class HttpxElevenLabsTransport:
    """HTTP transport for ElevenLabs text-to-speech."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = ELEVENLABS_API_BASE_URL,
        timeout_seconds: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = client

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        url = f"{self._base_url}{path}"
        headers = {"xi-api-key": self._api_key}
        if self._client is not None:
            return self._client.request(
                method,
                url,
                headers=headers,
                params=params,
                timeout=self._timeout_seconds,
            )
        with httpx.Client(timeout=self._timeout_seconds) as client:
            return client.request(method, url, headers=headers, params=params)

    def get_subscription(self) -> ElevenLabsSubscriptionSnapshot:
        response = self._request("GET", "/v1/user/subscription")
        if response.status_code >= 400:
            detail = response.text[:500]
            raise ElevenLabsApiError(
                f"ElevenLabs subscription lookup failed ({response.status_code}): {detail}",
                status_code=response.status_code,
            )
        payload = response.json()
        return ElevenLabsSubscriptionSnapshot(
            character_count=int(payload.get("character_count") or 0),
            character_limit=int(payload.get("character_limit") or 0),
            tier=str(payload.get("tier")) if payload.get("tier") else None,
        )

    def create_speech(
        self,
        *,
        voice_id: str,
        output_format: str,
        body: dict[str, Any],
    ) -> tuple[bytes, dict[str, str]]:
        url = f"{self._base_url}/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        params = {"output_format": output_format}

        if self._client is not None:
            response = self._client.post(
                url,
                headers=headers,
                params=params,
                json=body,
                timeout=self._timeout_seconds,
            )
        else:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(
                    url,
                    headers=headers,
                    params=params,
                    json=body,
                )

        if response.status_code >= 400:
            detail = response.text[:500]
            raise ElevenLabsApiError(
                f"ElevenLabs create speech failed ({response.status_code}): {detail}",
                status_code=response.status_code,
            )

        return response.content, dict(response.headers)


@dataclass(frozen=True, slots=True)
class ElevenLabsSubscriptionSnapshot:
    """Credits/characters available on the ElevenLabs account."""

    character_count: int
    character_limit: int
    tier: str | None = None

    @property
    def credits_remaining(self) -> int:
        return max(0, self.character_limit - self.character_count)


class ElevenLabsApiError(RuntimeError):
    """Raised when ElevenLabs returns a non-success response."""

    _JSON_SUFFIX = re.compile(r"\(\d+\):\s*(\{.*\})\s*$", re.DOTALL)

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    def _error_detail(self) -> dict[str, Any]:
        match = self._JSON_SUFFIX.search(str(self))
        if not match:
            return {}
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return {}
        detail = payload.get("detail")
        return detail if isinstance(detail, dict) else {}

    @property
    def provider_error_code(self) -> str | None:
        code = self._error_detail().get("code")
        return str(code) if code else None

    @property
    def is_quota_exceeded(self) -> bool:
        if self.provider_error_code == "quota_exceeded":
            return True
        return "quota_exceeded" in str(self).lower()

    @property
    def credits_remaining(self) -> int | None:
        message = self._error_detail().get("message") or str(self)
        match = re.search(r"You have (\d+) credits remaining", message)
        return int(match.group(1)) if match else None

    @property
    def credits_required(self) -> int | None:
        message = self._error_detail().get("message") or str(self)
        match = re.search(r"while (\d+) credits are required", message)
        return int(match.group(1)) if match else None


class ElevenLabsClient:
    """Provider boundary for single-chunk speech synthesis."""

    def __init__(self, transport: ElevenLabsTransport) -> None:
        self._transport = transport

    @classmethod
    def from_env(cls, *, api_key: str | None = None) -> ElevenLabsClient:
        key = api_key or require_elevenlabs_api_key()
        return cls(HttpxElevenLabsTransport(api_key=key))

    def synthesize(self, request: SpeechSynthesisRequest) -> SpeechSynthesisResult:
        audio_bytes, headers = self._transport.create_speech(
            voice_id=request.voice_id,
            output_format=request.output_format,
            body=request.to_api_body(),
        )
        return SpeechSynthesisResult.from_audio(
            audio_bytes,
            response_headers=headers,
            output_format=request.output_format,
        )

    def get_subscription(self) -> ElevenLabsSubscriptionSnapshot:
        transport = self._transport
        if not hasattr(transport, "get_subscription"):
            raise ElevenLabsApiError("Transport does not support subscription lookup")
        return transport.get_subscription()  # type: ignore[attr-defined]
