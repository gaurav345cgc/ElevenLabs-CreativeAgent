"""Enhancement job processor protocol for Agent 2."""

from __future__ import annotations

from typing import Protocol

from models.messages import EnhancementJobMessage


class EnhancementJobProcessor(Protocol):
    """Phase 8 implements the full ElevenLabs rewrite pipeline."""

    def process(self, message: EnhancementJobMessage) -> None: ...


class NotConfiguredEnhancementProcessor:
    """Placeholder until Phase 8 wires the enhancement engine."""

    def process(self, message: EnhancementJobMessage) -> None:
        raise RuntimeError(
            "Agent 2 enhancement engine is not implemented yet (Phase 8). "
            f"transcript_id={message.transcript_id} raw_version_id={message.raw_version_id}"
        )
