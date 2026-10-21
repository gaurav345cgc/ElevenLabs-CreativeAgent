"""Resolve Script Doctor mode and OpenAI settings for Agent 2."""

from __future__ import annotations

import os

from transcript_composer.llm_config import ensure_dotenv_loaded, resolve_openai_api_key


def resolve_script_doctor_mode() -> str:
    """auto | openai | deterministic"""
    ensure_dotenv_loaded()
    return os.environ.get("CREATIVE_AGENT_SCRIPT_DOCTOR", "auto").strip().lower() or "auto"
