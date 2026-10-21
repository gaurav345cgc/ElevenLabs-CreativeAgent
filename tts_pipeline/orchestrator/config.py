"""Orchestrator defaults — Step Functions Standard is the production target."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_ORCHESTRATOR = "step_functions_standard"


@dataclass(frozen=True, slots=True)
class StatePolicy:
    max_attempts: int
    timeout_seconds: int


# Retry/timeout guidance mirrored in infra/step_functions/tts_audio_job.asl.json
STATE_POLICIES: dict[str, StatePolicy] = {
    "ValidateInput": StatePolicy(max_attempts=1, timeout_seconds=30),
    "CreateAudioJob": StatePolicy(max_attempts=2, timeout_seconds=60),
    "LoadEnhancedTranscript": StatePolicy(max_attempts=2, timeout_seconds=60),
    "PlanPauses": StatePolicy(max_attempts=3, timeout_seconds=60),
    "PlanChunks": StatePolicy(max_attempts=2, timeout_seconds=120),
    "MapPausesToChunks": StatePolicy(max_attempts=2, timeout_seconds=30),
    "PersistChunkPlan": StatePolicy(max_attempts=2, timeout_seconds=60),
    "GenerateChunksSequentially": StatePolicy(max_attempts=1, timeout_seconds=900),
    "RegisterAssets": StatePolicy(max_attempts=2, timeout_seconds=60),
    "FinalizeFinal": StatePolicy(max_attempts=2, timeout_seconds=120),
    "MixBackground": StatePolicy(max_attempts=2, timeout_seconds=180),
    "FinalizeManifest": StatePolicy(max_attempts=2, timeout_seconds=30),
    "MarkCompleted": StatePolicy(max_attempts=2, timeout_seconds=30),
    "FailureHandler": StatePolicy(max_attempts=1, timeout_seconds=30),
}
