"""Build audio manifests, merge final narration, and mark TTS jobs complete."""

from tts_pipeline.finalizer.manifest import (
    MANIFEST_SCHEMA_VERSION,
    AudioJobManifest,
    ManifestChunkEntry,
    build_audio_job_manifest,
)
from tts_pipeline.finalizer.mix import BackgroundMixError, MixFn, mix_background
from tts_pipeline.finalizer.service import (
    FINAL_MERGED_EVENT,
    FINAL_SKIPPED_EVENT,
    MANIFEST_FINALIZED_EVENT,
    MANIFEST_SKIPPED_EVENT,
    MASTER_MIXED_EVENT,
    MASTER_SKIPPED_EVENT,
    FinalAudioMergeError,
    FinalizeFinalResult,
    FinalizeManifestResult,
    FinalizeMasterResult,
    ManifestFinalizationError,
    finalize_audio_job_final,
    finalize_audio_job_manifest,
    finalize_audio_job_master,
)
from tts_pipeline.finalizer.stitch import (
    FinalMergeError,
    merge_mp3_chunks,
    merge_mp3_chunks_with_holds,
)
from tts_pipeline.finalizer.silence import SilenceGenerationError, generate_silence_mp3

__all__ = [
    "FINAL_MERGED_EVENT",
    "FINAL_SKIPPED_EVENT",
    "MANIFEST_FINALIZED_EVENT",
    "MANIFEST_SCHEMA_VERSION",
    "MANIFEST_SKIPPED_EVENT",
    "MASTER_MIXED_EVENT",
    "MASTER_SKIPPED_EVENT",
    "AudioJobManifest",
    "BackgroundMixError",
    "FinalAudioMergeError",
    "FinalMergeError",
    "FinalizeFinalResult",
    "FinalizeManifestResult",
    "FinalizeMasterResult",
    "ManifestChunkEntry",
    "ManifestFinalizationError",
    "MixFn",
    "SilenceGenerationError",
    "build_audio_job_manifest",
    "finalize_audio_job_final",
    "finalize_audio_job_manifest",
    "finalize_audio_job_master",
    "generate_silence_mp3",
    "merge_mp3_chunks",
    "merge_mp3_chunks_with_holds",
    "mix_background",
]
