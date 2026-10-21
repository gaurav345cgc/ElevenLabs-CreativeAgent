"""Resolve OpenAI / model-provider credentials from environment or Secrets Manager."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DOTENV_LOADED = False


class ModelProviderConfigError(RuntimeError):
    """Raised when OpenAI generation is requested but no API key is available."""


def ensure_dotenv_loaded() -> None:
    """Load project .env so interactive Python and CLI pick up API keys."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = _PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
    _DOTENV_LOADED = True
    # First load may follow a cached miss; clear so auto mode re-checks keys.
    resolve_openai_api_key.cache_clear()


@lru_cache(maxsize=1)
def resolve_openai_api_key() -> str | None:
    """Load API key from env vars or AWS Secrets Manager."""
    ensure_dotenv_loaded()
    for env_name in ("CREATIVE_AGENT_OPENAI_API_KEY", "OPENAI_API_KEY"):
        value = os.environ.get(env_name, "").strip()
        if value:
            return value

    secret_arn = os.environ.get("CREATIVE_AGENT_MODEL_PROVIDER_SECRET_ARN", "").strip()
    if secret_arn:
        return _load_api_key_from_secrets_manager(secret_arn)
    return None


def require_openai_api_key() -> str:
    api_key = resolve_openai_api_key()
    if not api_key:
        raise ModelProviderConfigError(
            "OpenAI API key not configured. Set CREATIVE_AGENT_OPENAI_API_KEY, OPENAI_API_KEY, "
            "or CREATIVE_AGENT_MODEL_PROVIDER_SECRET_ARN."
        )
    return api_key


def resolve_openai_model() -> str:
    return os.environ.get("CREATIVE_AGENT_OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"


def resolve_script_generator_mode() -> str:
    """auto | openai | template"""
    ensure_dotenv_loaded()
    return os.environ.get("CREATIVE_AGENT_SCRIPT_GENERATOR", "auto").strip().lower() or "auto"


def resolve_validation_mode() -> str:
    """auto | openai | rules — how Agent 1 validates composed transcripts."""
    ensure_dotenv_loaded()
    return os.environ.get("CREATIVE_AGENT_TRANSCRIPT_VALIDATOR", "auto").strip().lower() or "auto"


def _load_api_key_from_secrets_manager(secret_arn: str) -> str:
    import boto3

    client = boto3.client("secretsmanager", region_name=_aws_region())
    response = client.get_secret_value(SecretId=secret_arn)
    payload = json.loads(response["SecretString"])
    api_key = payload.get("api_key") or payload.get("OPENAI_API_KEY")
    if not api_key:
        raise ModelProviderConfigError(
            f"Secret {secret_arn!r} does not contain api_key or OPENAI_API_KEY"
        )
    return str(api_key).strip()


def _aws_region() -> str:
    return os.environ.get("CREATIVE_AGENT_AWS_REGION", "us-east-1")
