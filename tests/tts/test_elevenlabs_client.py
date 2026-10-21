"""Phase 4 — ElevenLabs client tests (mocked provider)."""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest

from tts_pipeline.generator.config import (
    DEFAULT_APPLY_TEXT_NORMALIZATION,
    DEFAULT_ENABLE_LOGGING,
    DEFAULT_MODEL_ID,
    DEFAULT_OUTPUT_FORMAT,
)
from tts_pipeline.generator.elevenlabs_client import (
    ElevenLabsClient,
    HttpxElevenLabsTransport,
    PronunciationDictionaryLocator,
    SpeechSynthesisRequest,
    VoiceSettings,
)
from tts_pipeline.generator.chunk_synthesis import synthesize_and_store_chunk
from tts_pipeline.persistence.s3_audio import write_audio_object

TENANT = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
TRANSCRIPT = UUID("11111111-2222-3333-4444-555555555555")
JOB = UUID("66666666-7777-8888-9999-000000000000")


class FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def put_object(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}


def test_speech_request_defaults_match_phase_map() -> None:
    request = SpeechSynthesisRequest(text="Hello.", voice_id="voice_123")
    assert request.model_id == DEFAULT_MODEL_ID
    assert request.output_format == DEFAULT_OUTPUT_FORMAT
    assert request.apply_text_normalization == DEFAULT_APPLY_TEXT_NORMALIZATION
    assert request.enable_logging is DEFAULT_ENABLE_LOGGING


def test_speech_request_to_api_body_includes_all_supported_fields() -> None:
    request = SpeechSynthesisRequest(
        text="Breathe in.",
        voice_id="voice_123",
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
        voice_settings=VoiceSettings(stability=0.62, similarity_boost=0.78),
        seed=1337,
        apply_text_normalization="auto",
        enable_logging=True,
        pronunciation_dictionary_locators=[
            PronunciationDictionaryLocator(
                pronunciation_dictionary_id="dict_1",
                version_id="v1",
            )
        ],
        previous_text="Before.",
        next_text="After.",
        previous_request_ids=["req-prev"],
        next_request_ids=["req-next"],
    )
    body = request.to_api_body()
    assert body["text"] == "Breathe in."
    assert body["model_id"] == "eleven_multilingual_v2"
    assert body["voice_settings"]["stability"] == 0.62
    assert body["seed"] == 1337
    assert body["apply_text_normalization"] == "auto"
    assert body["enable_logging"] is True
    assert body["pronunciation_dictionary_locators"][0]["pronunciation_dictionary_id"] == "dict_1"
    assert body["previous_text"] == "Before."
    assert body["next_text"] == "After."
    assert body["previous_request_ids"] == ["req-prev"]
    assert body["next_request_ids"] == ["req-next"]


def test_client_captures_request_id_checksum_and_headers() -> None:
    fake_audio = b"\xff\xfb\x90\x00fake-mp3-bytes"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1/text-to-speech/voice_abc")
        assert request.url.params["output_format"] == "mp3_44100_128"
        assert request.headers["xi-api-key"] == "test-key"
        payload = httpx.Response(200, content=fake_audio, headers={"request-id": "req-123"})
        payload.headers["character-cost"] = "42"
        return payload

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = ElevenLabsClient(
        HttpxElevenLabsTransport(api_key="test-key", client=http_client)
    )

    result = client.synthesize(
        SpeechSynthesisRequest(text="Settle in.", voice_id="voice_abc")
    )

    assert result.audio_bytes == fake_audio
    assert result.request_id == "req-123"
    assert result.response_headers["character-cost"] == "42"
    assert result.byte_size == len(fake_audio)
    assert len(result.checksum_sha256) == 64


def test_synthesize_and_store_chunk_writes_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_audio = b"\xff\xfb\x90\x00chunk-audio"

    class StubTransport:
        def create_speech(self, *, voice_id: str, output_format: str, body: dict) -> tuple[bytes, dict[str, str]]:
            assert voice_id == "voice_abc"
            assert body["text"] == "Relax."
            return fake_audio, {"request-id": "req-999", "character-cost": "12"}

    fake_s3 = FakeS3Client()
    monkeypatch.setenv("CREATIVE_AGENT_TTS_AUDIO_BUCKET", "test-bucket")

    stored = synthesize_and_store_chunk(
        ElevenLabsClient(StubTransport()),
        SpeechSynthesisRequest(text="Relax.", voice_id="voice_abc"),
        tenant_id=TENANT,
        transcript_id=TRANSCRIPT,
        audio_job_id=JOB,
        chunk_index=0,
        bucket="test-bucket",
        s3_client=fake_s3,
    )

    assert stored.result.request_id == "req-999"
    assert stored.stored.bucket == "test-bucket"
    assert stored.stored.object_key.endswith("/chunks/0.mp3")
    assert stored.stored.byte_size == len(fake_audio)
    assert fake_s3.calls[0]["Key"].endswith("/chunks/0.mp3")


def test_write_audio_object_uses_boto3_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_s3 = FakeS3Client()
    stored = write_audio_object(
        bucket="test-bucket",
        object_key="tenant/transcript/job/chunks/0.mp3",
        audio_bytes=b"abc",
        checksum_sha256="deadbeef",
        mime_type="audio/mpeg",
        s3_client=fake_s3,
        metadata={"request-id": "req-1"},
    )
    assert stored.byte_size == 3
    assert fake_s3.calls[0]["Bucket"] == "test-bucket"
    assert fake_s3.calls[0]["ContentType"] == "audio/mpeg"
    assert fake_s3.calls[0]["Metadata"]["request-id"] == "req-1"
