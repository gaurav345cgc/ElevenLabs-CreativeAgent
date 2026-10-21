"""ElevenLabs TTS client defaults and credential resolution."""

from __future__ import annotations

import json
import os
from functools import lru_cache

from transcript_composer.llm_config import ensure_dotenv_loaded

DEFAULT_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_APPLY_TEXT_NORMALIZATION = "auto"
DEFAULT_ENABLE_LOGGING = True
DEFAULT_MIME_TYPE = "audio/mpeg"
ELEVENLABS_API_BASE_URL = "https://api.elevenlabs.io"


class ElevenLabsConfigError(RuntimeError):
    """Raised when ElevenLabs TTS is requested but no API key is available."""


@lru_cache(maxsize=1)
def resolve_elevenlabs_api_key() -> str | None:
    """Load ElevenLabs API key from environment or Secrets Manager."""
    ensure_dotenv_loaded()
    for env_name in ("CREATIVE_AGENT_ELEVENLABS_API_KEY", "ELEVENLABS_API_KEY"):
        value = os.environ.get(env_name, "").strip()
        if value:
            return value

    secret_arn = os.environ.get("CREATIVE_AGENT_ELEVENLABS_SECRET_ARN", "").strip()
    if secret_arn:
        return _load_api_key_from_secrets_manager(secret_arn)
    return None


def require_elevenlabs_api_key() -> str:
    api_key = resolve_elevenlabs_api_key()
    if not api_key:
        raise ElevenLabsConfigError(
            "ElevenLabs API key not configured. Set CREATIVE_AGENT_ELEVENLABS_API_KEY, "
            "ELEVENLABS_API_KEY, or CREATIVE_AGENT_ELEVENLABS_SECRET_ARN."
        )
    return api_key


def resolve_tts_audio_bucket() -> str | None:
    ensure_dotenv_loaded()
    value = os.environ.get("CREATIVE_AGENT_TTS_AUDIO_BUCKET", "").strip()
    return value or None


def _load_api_key_from_secrets_manager(secret_arn: str) -> str:
    import boto3

    region = os.environ.get("CREATIVE_AGENT_AWS_REGION", "us-east-1")
    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_arn)
    payload = json.loads(response["SecretString"])
    api_key = payload.get("api_key") or payload.get("elevenlabs_api_key")
    if not api_key:
        raise ElevenLabsConfigError(
            f"Secret {secret_arn!r} does not contain api_key or elevenlabs_api_key"
        )
    return str(api_key).strip()
