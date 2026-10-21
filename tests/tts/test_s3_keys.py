"""TTS S3 key layout tests."""

from uuid import UUID

from tts_pipeline.persistence.s3_keys import (
    background_track_key,
    chunk_object_key,
    debug_request_object_key,
    final_object_key,
    job_prefix,
    manifest_object_key,
    master_object_key,
)

TENANT = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
TRANSCRIPT = UUID("11111111-2222-3333-4444-555555555555")
JOB = UUID("66666666-7777-8888-9999-000000000000")


def test_job_prefix():
    assert job_prefix(TENANT, TRANSCRIPT, JOB) == (
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/"
        "11111111-2222-3333-4444-555555555555/"
        "66666666-7777-8888-9999-000000000000/"
    )


def test_chunk_object_key():
    assert chunk_object_key(TENANT, TRANSCRIPT, JOB, 3) == (
        f"{job_prefix(TENANT, TRANSCRIPT, JOB)}chunks/3.mp3"
    )


def test_final_object_key():
    assert final_object_key(TENANT, TRANSCRIPT, JOB).endswith("final/final.mp3")


def test_master_object_key_matches_job_prefix_pattern():
    key = master_object_key(TENANT, TRANSCRIPT, JOB)
    assert key == f"{job_prefix(TENANT, TRANSCRIPT, JOB)}final/master.mp3"
    assert key.endswith("final/master.mp3")


def test_background_track_key_format():
    assert background_track_key("calm_ambient_01") == "background/calm_ambient_01.mp3"


def test_manifest_object_key():
    assert manifest_object_key(TENANT, TRANSCRIPT, JOB).endswith(
        "manifest/audio_manifest.json"
    )


def test_debug_request_object_key():
    assert debug_request_object_key(TENANT, TRANSCRIPT, JOB, 0).endswith(
        "debug/request-0.json"
    )


def test_debug_object_tags():
    from tts_pipeline.persistence.s3_keys import debug_object_tags

    assert debug_object_tags() == {"artifact_kind": "debug"}
