"""Domain enums shared by schema, API, and agents."""

from enum import StrEnum


class TranscriptStatus(StrEnum):
    CREATED = "CREATED"
    PENDING_ENHANCEMENT = "PENDING_ENHANCEMENT"
    ENHANCING = "ENHANCING"
    ENHANCED = "ENHANCED"
    APPROVED = "APPROVED"
    FAILED_ENHANCEMENT = "FAILED_ENHANCEMENT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class VersionKind(StrEnum):
    RAW_PATTERN = "RAW_PATTERN"
    ELEVENLABS_ENHANCED = "ELEVENLABS_ENHANCED"
    ELEVENLABS_TAGGED = "ELEVENLABS_TAGGED"
    APPROVED_FINAL = "APPROVED_FINAL"


class EnhancementMode(StrEnum):
    """Agent 2 output mode; used for idempotent enhanced version uniqueness."""

    PLAIN_PASTE = "plain_paste"
    API_CHUNKED = "api_chunked"
    V3_TAGGED = "v3_tagged"


class AudioJobStatus(StrEnum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    READY = "READY"
    GENERATING = "GENERATING"
    PARTIALLY_FAILED = "PARTIALLY_FAILED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class AudioChunkStatus(StrEnum):
    PLANNED = "PLANNED"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    SKIPPED = "SKIPPED"


class AudioAssetKind(StrEnum):
    CHUNK = "chunk"
    FINAL = "final"
    MASTER = "master"
    MANIFEST = "manifest"
    DEBUG = "debug"


TRANSCRIPT_STATUS_VALUES = tuple(s.value for s in TranscriptStatus)
VERSION_KIND_VALUES = tuple(v.value for v in VersionKind)
ENHANCEMENT_MODE_VALUES = tuple(m.value for m in EnhancementMode)
AUDIO_JOB_STATUS_VALUES = tuple(s.value for s in AudioJobStatus)
AUDIO_CHUNK_STATUS_VALUES = tuple(s.value for s in AudioChunkStatus)
AUDIO_ASSET_KIND_VALUES = tuple(k.value for k in AudioAssetKind)
