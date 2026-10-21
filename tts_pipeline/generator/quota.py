"""ElevenLabs credit preflight and quota error helpers."""

from __future__ import annotations

from models.enums import AudioChunkStatus
from models.records import TranscriptAudioChunkRecord, TranscriptAudioJobRecord
from observability.tts import log_tts_job_failed
from tts_pipeline.generator.elevenlabs_client import ElevenLabsClient, ElevenLabsSubscriptionSnapshot


class QuotaExceededError(RuntimeError):
    """ElevenLabs account does not have enough credits for pending synthesis."""

    def __init__(
        self,
        message: str,
        *,
        credits_remaining: int | None = None,
        credits_required: int | None = None,
    ) -> None:
        super().__init__(message)
        self.credits_remaining = credits_remaining
        self.credits_required = credits_required


def chunks_pending_synthesis(
    chunks: list[TranscriptAudioChunkRecord],
) -> list[TranscriptAudioChunkRecord]:
    pending: list[TranscriptAudioChunkRecord] = []
    for chunk in chunks:
        if chunk.status is AudioChunkStatus.COMPLETED and chunk.output_object_key:
            continue
        pending.append(chunk)
    return sorted(pending, key=lambda item: item.chunk_index)


def estimate_credits_for_chunks(chunks: list[TranscriptAudioChunkRecord]) -> int:
    """Conservative credit estimate — one credit per source character."""
    return sum(max(chunk.character_count, len(chunk.source_text)) for chunk in chunks)


def assert_sufficient_credits_for_pending_chunks(
    client: ElevenLabsClient,
    job: TranscriptAudioJobRecord,
    chunks: list[TranscriptAudioChunkRecord],
) -> ElevenLabsSubscriptionSnapshot:
    pending = chunks_pending_synthesis(chunks)
    if not pending:
        return ElevenLabsSubscriptionSnapshot(character_count=0, character_limit=0)

    required = estimate_credits_for_chunks(pending)
    subscription = client.get_subscription()
    remaining = subscription.credits_remaining

    if required > remaining:
        message = (
            f"ElevenLabs quota insufficient for audio job {job.id}: "
            f"need ~{required} credits for {len(pending)} pending chunk(s), "
            f"but only {remaining} credits remain "
            f"(limit {subscription.character_limit}, tier {subscription.tier or 'unknown'}). "
            "Top up ElevenLabs credits or wait for the monthly reset."
        )
        log_tts_job_failed(
            audio_job_id=str(job.id),
            transcript_id=str(job.transcript_id),
            error=message,
            error_code="QuotaExceeded",
            credits_remaining=remaining,
            credits_required=required,
            pending_chunks=len(pending),
        )
        raise QuotaExceededError(
            message,
            credits_remaining=remaining,
            credits_required=required,
        )

    return subscription
