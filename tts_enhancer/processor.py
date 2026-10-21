"""Bridge SQS job messages to the Agent 2 enhancement service."""

from __future__ import annotations

from models.messages import EnhancementJobMessage
from queues.processor import EnhancementJobProcessor
from tts_enhancer.enhancement_service import EnhancementService


class EnhancementJobProcessorImpl(EnhancementJobProcessor):
    def __init__(self, *, service: EnhancementService | None = None) -> None:
        self._service = service or EnhancementService()

    def process(self, message: EnhancementJobMessage) -> None:
        self._service.run(message)
