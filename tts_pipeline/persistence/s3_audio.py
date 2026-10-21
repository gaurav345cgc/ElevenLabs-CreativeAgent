"""Write synthesized audio bytes to the TTS S3 bucket."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from tts_pipeline.generator.config import resolve_tts_audio_bucket


@dataclass(frozen=True, slots=True)
class StoredAudioObject:
    bucket: str
    object_key: str
    byte_size: int
    checksum_sha256: str
    mime_type: str


class S3PutObjectClient(Protocol):
    def put_object(self, **kwargs) -> dict: ...


class S3GetObjectClient(Protocol):
    def get_object(self, **kwargs) -> dict: ...


def write_audio_object(
    *,
    object_key: str,
    audio_bytes: bytes,
    checksum_sha256: str,
    mime_type: str,
    bucket: str | None = None,
    s3_client: S3PutObjectClient | None = None,
    metadata: dict[str, str] | None = None,
    tags: dict[str, str] | None = None,
) -> StoredAudioObject:
    """Persist one audio artifact to S3."""
    target_bucket = bucket or resolve_tts_audio_bucket()
    if not target_bucket:
        raise ValueError(
            "TTS audio bucket not configured. Set CREATIVE_AGENT_TTS_AUDIO_BUCKET."
        )

    client = s3_client or _default_s3_client()
    put_kwargs: dict = {
        "Bucket": target_bucket,
        "Key": object_key,
        "Body": audio_bytes,
        "ContentType": mime_type,
        "Metadata": metadata or {},
    }
    if tags:
        put_kwargs["Tagging"] = _encode_tagging(tags)

    client.put_object(**put_kwargs)
    return StoredAudioObject(
        bucket=target_bucket,
        object_key=object_key,
        byte_size=len(audio_bytes),
        checksum_sha256=checksum_sha256,
        mime_type=mime_type,
    )


def write_json_object(
    *,
    object_key: str,
    payload: bytes,
    checksum_sha256: str,
    mime_type: str = "application/json",
    bucket: str | None = None,
    s3_client: S3PutObjectClient | None = None,
    metadata: dict[str, str] | None = None,
) -> StoredAudioObject:
    """Persist one JSON artifact to S3."""
    return write_audio_object(
        object_key=object_key,
        audio_bytes=payload,
        checksum_sha256=checksum_sha256,
        mime_type=mime_type,
        bucket=bucket,
        s3_client=s3_client,
        metadata=metadata,
    )


def read_object_bytes(
    *,
    object_key: str,
    bucket: str | None = None,
    s3_client: S3GetObjectClient | None = None,
) -> bytes:
    """Read one S3 object body."""
    target_bucket = bucket or resolve_tts_audio_bucket()
    if not target_bucket:
        raise ValueError(
            "TTS audio bucket not configured. Set CREATIVE_AGENT_TTS_AUDIO_BUCKET."
        )

    client = s3_client or _default_s3_client()
    response = client.get_object(Bucket=target_bucket, Key=object_key)
    body = response["Body"]
    if hasattr(body, "read"):
        return body.read()
    return bytes(body)


def generate_presigned_object_url(
    *,
    object_key: str,
    bucket: str | None = None,
    expires_in: int = 3600,
    s3_client=None,
) -> str:
    """Return a time-limited HTTPS URL for one S3 object."""
    target_bucket = bucket or resolve_tts_audio_bucket()
    if not target_bucket:
        raise ValueError(
            "TTS audio bucket not configured. Set CREATIVE_AGENT_TTS_AUDIO_BUCKET."
        )

    client = s3_client or _default_s3_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": target_bucket, "Key": object_key},
        ExpiresIn=expires_in,
    )


def _default_s3_client() -> S3PutObjectClient:
    import boto3

    return boto3.client("s3")


def _encode_tagging(tags: dict[str, str]) -> str:
    return "&".join(f"{key}={value}" for key, value in tags.items())
