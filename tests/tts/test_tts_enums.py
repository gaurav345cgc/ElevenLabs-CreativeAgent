"""TTS domain enum contracts."""

from models.enums import (
    AUDIO_ASSET_KIND_VALUES,
    AUDIO_CHUNK_STATUS_VALUES,
    AUDIO_JOB_STATUS_VALUES,
    AudioAssetKind,
    AudioChunkStatus,
    AudioJobStatus,
)


def test_audio_job_status_values_match_phase_map() -> None:
    expected = {
        "CREATED",
        "PLANNING",
        "READY",
        "GENERATING",
        "PARTIALLY_FAILED",
        "COMPLETED",
        "FAILED",
        "REVIEW_REQUIRED",
    }
    assert set(AUDIO_JOB_STATUS_VALUES) == expected
    assert AudioJobStatus.COMPLETED.value == "COMPLETED"


def test_audio_chunk_status_values_match_phase_map() -> None:
    expected = {"PLANNED", "GENERATING", "COMPLETED", "FAILED", "RETRYING", "SKIPPED"}
    assert set(AUDIO_CHUNK_STATUS_VALUES) == expected
    assert AudioChunkStatus.PLANNED.value == "PLANNED"


def test_audio_asset_kinds() -> None:
    assert set(AUDIO_ASSET_KIND_VALUES) == {"chunk", "final", "master", "manifest", "debug"}
    assert AudioAssetKind.MANIFEST.value == "manifest"


def test_audio_asset_kind_master_value() -> None:
    assert AudioAssetKind.MASTER.value == "master"
