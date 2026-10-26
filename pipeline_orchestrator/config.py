"""Runtime configuration for the pipeline orchestrator."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID


DEFAULT_TENANT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
DEFAULT_API_BASE = "https://vwhmjhoym3.execute-api.us-east-1.amazonaws.com"
DEFAULT_VOICE_PROFILE = "drew_primary"


def _read_env_file_value(name: str, root: Path) -> str | None:
    env_file = root / ".env"
    if not env_file.is_file():
        return None
    prefix = f"{name}="
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip().strip('"').strip("'")
    return None


def resolve_api_key(*, override: str | None = None, project_root: Path | None = None) -> str:
    if override:
        return override
    if key := os.environ.get("CREATIVE_AGENT_API_KEY"):
        return key

    root = project_root or Path(__file__).resolve().parents[1]
    if from_env := _read_env_file_value("CREATIVE_AGENT_API_KEY", root):
        return from_env

    key_file = root / "infra" / "terraform" / "build" / "deployed_api_key.txt"
    if key_file.is_file():
        return key_file.read_text(encoding="utf-8").strip()

    raise ValueError(
        "Missing API key. Set CREATIVE_AGENT_API_KEY in .env or pass api_key to the orchestrator."
    )


@dataclass(frozen=True)
class OrchestratorSettings:
    api_base_url: str
    api_key: str
    tenant_id: UUID
    poll_seconds: float = 15.0
    enhancement_timeout_seconds: float = 15 * 60
    tts_timeout_seconds: float = 25 * 60
    max_compose_retries: int = 2
    max_compose_repair_attempts: int = 3
    max_enhance_retries: int = 3
    max_tts_retries: int = 3
    max_brain_steps: int = 24
    max_third_party_retries: int = 3
    third_party_retry_backoff_seconds: float = 5.0
    api_request_retries: int = 3
    voice_profile_code: str = DEFAULT_VOICE_PROFILE
    output_dir: Path = field(default_factory=lambda: Path("output"))
    accept_partial_tts: bool = False
    orchestrator_mode: str = "auto"  # auto | agentic | graph

    @classmethod
    def from_env(
        cls,
        *,
        api_key: str | None = None,
        api_base_url: str | None = None,
        tenant_id: UUID | str | None = None,
        project_root: Path | None = None,
    ) -> OrchestratorSettings:
        root = project_root or Path(__file__).resolve().parents[1]
        resolved_base = (
            api_base_url
            or os.environ.get("CREATIVE_AGENT_API_GATEWAY_URL")
            or DEFAULT_API_BASE
        ).rstrip("/")
        resolved_tenant = (
            UUID(str(tenant_id)) if tenant_id is not None else DEFAULT_TENANT_ID
        )
        output = root / "output"
        return cls(
            api_base_url=resolved_base,
            api_key=resolve_api_key(override=api_key, project_root=root),
            tenant_id=resolved_tenant,
            output_dir=output,
        )
