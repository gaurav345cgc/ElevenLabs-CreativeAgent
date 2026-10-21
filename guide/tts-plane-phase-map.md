# TTS Plane — Phase Map and Build Checklist

This is the implementation checklist for the **ElevenLabs TTS Orchestration Plane**. It starts from the already-completed transcript pipeline and ends at stored audio artifacts and manifests.

**Master architecture:** [`architecture-and-tts-plane.md`](architecture-and-tts-plane.md)

This document assumes the following is already complete and stable:

- Agent 1 composes a base transcript.
- Agent 2 enhances it into `ELEVENLABS_ENHANCED`.
- Aurora stores transcript versions.
- The API Lambda exposes status and versions.
- The repo already contains `api/`, `transcript_composer/`, `tts_enhancer/`, `db/`, `queues/`, `models/`, `observability/`, `guide/`, `infra/`, `scripts/`, and `tests/`.

This phase map is only for the next downstream plane: **transcript to voice generation**.

---

## 0) What this plane does

The TTS plane:

1. Reads an `ELEVENLABS_ENHANCED` transcript version.
2. Creates a TTS job.
3. Plans text chunks for synthesis.
4. Calls ElevenLabs Create speech.
5. Stores audio chunks in S3.
6. Stores metadata in Aurora.
7. Builds a final manifest.
8. Marks the audio job complete.

The ElevenLabs TTS API supports the controls this plane needs, including `voice_id`, `model_id`, `output_format`, `voice_settings`, `seed`, pronunciation dictionaries, and continuity fields like `previous_text`, `next_text`, `previous_request_ids`, and `next_request_ids`.

---

## 1) Phase 0 — boundary definition

### Goal

Lock the plane boundary before writing code.

### Checklist

- [x] Confirm the TTS plane starts only after transcript status is `ENHANCED`.
- [x] Confirm the TTS plane does not rewrite transcript meaning.
- [x] Confirm the TTS plane stores audio artifacts in S3, not in Aurora.
- [x] Confirm the TTS plane will be a separate `tts_pipeline/` segment folder.
- [x] Confirm the TTS plane will remain in the same repo as the transcript pipeline.
- [x] Confirm the TTS plane will use a voice policy layer rather than raw caller-controlled provider params.
- [x] Confirm the TTS plane will be idempotent at chunk level.
- [x] Confirm the TTS plane will support partial regeneration.
- [x] Confirm the TTS plane will preserve request metadata for debugging and cost tracking.

### Exit criteria

- [x] Boundary and responsibilities are approved — [`phase-tts-0-boundary.md`](phase-tts-0-boundary.md).
- [x] No overlap with transcript enhancement logic remains.

---

## 2) Phase 1 — repo and folder additions

### Goal

Add the TTS segment to the monorepo without disturbing the completed transcript system.

### Checklist

- [x] Create `tts_pipeline/` at repo root.
- [x] Add `tts_pipeline/intake/`.
- [x] Add `tts_pipeline/orchestrator/`.
- [x] Add `tts_pipeline/chunk_planner/`.
- [x] Add `tts_pipeline/generator/`.
- [x] Add `tts_pipeline/finalizer/`.
- [x] Add `tts_pipeline/voice_policy/`.
- [x] Add `tts_pipeline/persistence/`.
- [x] Add TTS tests under `tests/tts/` or equivalent.
- [x] Add TTS docs references under `guide/`.
- [x] Add TTS schema migrations under `db/migrations/`.
- [x] Update README with the new downstream plane summary.
- [x] Update `.cursor/rules/` with TTS plane invariants.

### Exit criteria

- [x] Repo contains a clean, isolated TTS segment.
- [x] Existing transcript code remains unchanged.

---

## 3) Phase 2 — data model

### Goal

Add the persistent objects needed for TTS jobs, chunks, and final assets.

### Checklist

- [x] Create `transcript_audio_job` table.
- [x] Create `transcript_audio_chunk` table.
- [x] Create `transcript_audio_asset` table.
- [x] Create `transcript_audio_event` table.
- [x] Add job status enum.
- [x] Add chunk status enum.
- [x] Add indexes for `transcript_id`, `transcript_version_id`, `status`, `audio_job_id`, `chunk_index`.
- [x] Add uniqueness constraint on `(audio_job_id, chunk_index)`.
- [x] Add foreign key from TTS job to transcript version.
- [x] Add foreign key from chunks to job.
- [x] Add `final_asset_id` pointer on job.
- [x] Add retry counters and failure notes.
- [x] Add response metadata JSON fields.
- [x] Add audit event recording for job lifecycle transitions.

### Suggested job statuses

- [x] `CREATED`
- [x] `PLANNING`
- [x] `READY`
- [x] `GENERATING`
- [x] `PARTIALLY_FAILED`
- [x] `COMPLETED`
- [x] `FAILED`
- [x] `REVIEW_REQUIRED`

### Suggested chunk statuses

- [x] `PLANNED`
- [x] `GENERATING`
- [x] `COMPLETED`
- [x] `FAILED`
- [x] `RETRYING`
- [x] `SKIPPED`

### Exit criteria

- [x] Migrations apply cleanly.
- [x] Query patterns are supported.
- [x] No audio data is stored in transcript tables.

---

## 4) Phase 3 — S3 and IAM

### Goal

Provision object storage for audio artifacts and secure access from the TTS plane.

### Checklist

- [x] Create S3 bucket for TTS audio artifacts.
- [x] Define bucket prefix strategy.
- [x] Add IAM permissions for write/read access.
- [x] Add lifecycle policy if needed.
- [x] Add encryption at rest.
- [x] Add object ownership and access constraints.
- [x] Add optional KMS key if required by policy.
- [x] Define a debug prefix for request/response metadata.
- [x] Define a final prefix for merged or finalized audio assets.
- [x] Define a chunks prefix for per-chunk artifacts.

### Recommended S3 layout

- [x] `s3://tts-audio/{tenant_id}/{transcript_id}/{audio_job_id}/chunks/{chunk_index}.mp3`
- [x] `s3://tts-audio/{tenant_id}/{transcript_id}/{audio_job_id}/final/final.mp3`
- [x] `s3://tts-audio/{tenant_id}/{transcript_id}/{audio_job_id}/manifest/audio_manifest.json`
- [x] `s3://tts-audio/{tenant_id}/{transcript_id}/{audio_job_id}/debug/request-{chunk_index}.json`

### Exit criteria

- [x] Audio artifacts can be safely stored and retrieved.
- [x] IAM scope is least privilege.

---

## 5) Phase 4 — ElevenLabs integration layer

### Goal

Wrap the provider API behind a controlled client boundary.

### Checklist

- [x] Create `tts_pipeline/generator/elevenlabs_client.py` or equivalent.
- [x] Add support for `voice_id`.
- [x] Add support for `model_id`.
- [x] Add support for `output_format`.
- [x] Add support for `voice_settings`.
- [x] Add support for `seed`.
- [x] Add support for `apply_text_normalization`.
- [x] Add support for pronunciation dictionaries.
- [x] Add support for `previous_text`.
- [x] Add support for `next_text`.
- [x] Add support for `previous_request_ids`.
- [x] Add support for `next_request_ids`.
- [x] Add support for `enable_logging`.
- [x] Persist provider request IDs.
- [x] Persist response headers where possible.
- [x] Persist byte size and checksum information.
- [x] Add tests against mocked provider responses.

### Recommended defaults

- [x] `model_id = eleven_multilingual_v2`
- [x] `output_format = mp3_44100_128`
- [x] `apply_text_normalization = auto`
- [x] `enable_logging = true`

### Exit criteria

- [x] A single chunk can be synthesized and written to S3.
- [x] Provider metadata is captured.

---

## 6) Phase 5 — voice policy

### Goal

Prevent arbitrary or inconsistent voice configuration.

### Checklist

- [x] Define voice profile schema.
- [x] Define approved voice profiles in code or config.
- [x] Map voice profile to ElevenLabs `voice_id`.
- [x] Map voice profile to default `model_id`.
- [x] Map voice profile to output format.
- [x] Define allowed `voice_settings` bounds.
- [x] Define allowed seed behavior.
- [x] Define pronunciation dictionary policy.
- [x] Define when `enable_logging=false` is allowed, if ever.
- [x] Define whether expressive mode is allowed for any profile.

### Exit criteria

- [x] Voice selection is policy-driven, not raw caller-driven.
- [x] Default narration settings are stable and repeatable.

---

## 7) Phase 6 — transcript ingestion

### Goal

Load enhanced transcript versions and create audio jobs from them.

### Checklist

- [x] Create job intake service.
- [x] Validate transcript exists.
- [x] Validate transcript version exists.
- [x] Validate transcript version kind is `ELEVENLABS_ENHANCED`.
- [x] Validate transcript is in an allowed state.
- [x] Create audio job row.
- [x] Record job-created event.
- [x] Capture transcript metadata for traceability.
- [x] Save voice profile selection.
- [x] Save model and format selection.
- [x] Save normalization policy.
- [x] Save optional seed.

### Exit criteria

- [x] A transcript version can become a TTS job.
- [x] Job state is persisted before generation begins.

---

## 8) Phase 7 — chunk planning

### Goal

Split the enhanced transcript into speech-friendly generation chunks.

### Checklist

- [x] Prefer beat boundaries created by Agent 2.
- [x] If no beats exist, fall back to paragraph boundaries.
- [x] If needed, fall back to sentence grouping.
- [x] Avoid mid-sentence splits.
- [x] Avoid splitting on weak connectors.
- [x] Preserve spoken rhythm.
- [x] Build `previous_text` and `next_text` for each chunk.
- [x] Estimate character count per chunk.
- [x] Estimate duration per chunk.
- [x] Persist chunk plan before generation.
- [x] Add validation for minimum and maximum chunk size.
- [x] Add tests for chunk boundary quality.

### Exit criteria

- [x] Chunk plan exists independently of generation.
- [x] The chunk plan is inspectable and replayable.

---

## 9) Phase 8 — orchestration engine

### Goal

Drive the job through its lifecycle in a durable way.

### Checklist

- [x] Choose Step Functions Standard as the default orchestrator.
- [x] Define the state machine.
- [x] Add validation state.
- [x] Add job creation state.
- [x] Add transcript load state.
- [x] Add chunk planning state.
- [x] Add chunk persistence state.
- [x] Add sequential generation state.
- [x] Add finalization state.
- [x] Add failure handling state.
- [x] Add retry policy per state.
- [x] Add timeout policy per state.
- [x] Add execution logging.
- [x] Add execution correlation IDs.

### Recommended state machine steps

- [x] `ValidateInput`
- [x] `CreateAudioJob`
- [x] `LoadEnhancedTranscript`
- [x] `PlanChunks`
- [x] `PersistChunkPlan`
- [x] `GenerateChunksSequentially`
- [x] `RegisterAssets`
- [x] `FinalizeManifest`
- [x] `MarkCompleted`
- [x] `FailureHandler`

### Exit criteria

- [x] A job can move from planning to completion through a durable workflow.
- [x] Failures are handled in a predictable place.

---

## 10) Phase 9 — chunk generation

### Goal

Generate audio chunk by chunk and persist outputs safely.

### Checklist

- [x] For each chunk, build provider request payload.
- [x] Include continuity fields.
- [x] Call ElevenLabs.
- [x] Write audio bytes to S3.
- [x] Record provider request ID.
- [x] Record response headers.
- [x] Record checksum and byte size.
- [x] Update chunk row to `COMPLETED`.
- [x] Update job completed chunk count.
- [x] Emit chunk event.
- [x] Support retry for transient failures.
- [x] Support no-duplicate behavior on retried successful chunks.

### Continuity rules

- [x] Use `previous_text` / `next_text` for first-pass generation.
- [x] Use `previous_request_ids` / `next_request_ids` for regeneration.
- [x] Prefer sequential generation for meditation audio.
- [x] Keep model consistent across chunks.

### Exit criteria

- [x] Multiple chunks can be generated safely.
- [x] One failed chunk does not destroy the job.

---

## 11) Phase 10 — retry and idempotency

### Goal

Make generation safe under retries and duplicate execution.

### Checklist

- [x] Define chunk-level idempotency key.
- [x] Define job-level idempotency key.
- [x] Make DB writes conditional where needed.
- [x] Prevent duplicate successful chunk writes.
- [x] Return existing chunk artifact if already completed.
- [x] Retry only transient failures.
- [x] Use `previous_request_ids` and `next_request_ids` for middle-chunk regeneration.
- [x] Avoid indefinite retry loops.
- [x] Mark jobs `PARTIALLY_FAILED` when only some chunks fail.
- [x] Escalate jobs to `REVIEW_REQUIRED` if necessary.
- [x] Add explicit replay endpoint or operator path later if needed.

### Exit criteria

- [x] Duplicate calls do not create duplicate outputs.
- [x] Chunk retries are safe and deterministic.

**Notes:** Chunk identity is `build_chunk_idempotency_key()` / `(audio_job_id, chunk_index)` with a deterministic S3 key. Job identity is `build_audio_job_idempotency_key()` with a DB unique constraint. Skip-before-synthesize, conditional DB writes, and `COMPLETED` job re-entry cover duplicate execution. Permanent provider/config failures and repeated workflow retries escalate to `REVIEW_REQUIRED`; transient partial failures remain `PARTIALLY_FAILED`. Operator replay: `scripts/run_tts_workflow_smoke.py` with `--start-at`.

---

## 12) Phase 11 — finalization and manifest

### Goal

Create the final representation of the completed audio job.

### Checklist

- [x] Collect all completed chunk rows.
- [x] Build a final manifest JSON.
- [x] Persist manifest to S3.
- [x] Persist final asset row if a merged output exists.
- [x] Set job `final_asset_id`.
- [x] Mark job `COMPLETED`.
- [x] Write a job-completed event.
- [x] Expose manifest through API later if needed.

### Manifest should include

- [x] transcript ID
- [x] transcript version ID
- [x] audio job ID
- [x] voice ID
- [x] model ID
- [x] output format
- [x] chunk list
- [x] request IDs
- [x] S3 object keys
- [x] per-chunk duration
- [x] total duration
- [x] status

### Exit criteria

- [x] Every completed job has a manifest.
- [x] Audio assets can be consumed downstream without DB reconstruction.

**Notes:** `tts_pipeline/finalizer/` merges chunk MP3s to `final/final.mp3` via ffmpeg re-encode, registers a `final` asset row, sets `job.final_asset_id`, builds `audio_manifest.json` (including final fields), writes to S3, and registers a `manifest` asset row. API: `GET /audio-jobs/{id}` and `GET /audio-jobs/{id}/manifest`. Backfill: `scripts/finalize_manifest_smoke.py --audio-job-id <uuid>`.

---

## 13) Phase 12 — observability

### Goal

Make the TTS plane operable.

### Checklist

- [x] Add structured logs.
- [x] Include job IDs, chunk IDs, request IDs, and transcript IDs in logs.
- [x] Add metrics for jobs created, jobs completed, jobs failed.
- [x] Add metrics for chunk failures and retries.
- [x] Add metrics for provider latency.
- [x] Add metrics for storage failures.
- [x] Add metrics for DB write failures.
- [x] Add dashboard for TTS throughput and health.
- [x] Add alarms for failures and backlog.
- [x] Add alarm for abnormal cost growth.
- [x] Add alarm for repeated partial failures.
- [x] Add job replay diagnostic logs.

### Exit criteria

- [x] Operators can see job health quickly.
- [x] Failures are diagnosable without code changes.

**Notes:** `observability/tts.py` emits JSON logs (`creative_agent.tts`) and CloudWatch EMF metrics (`CreativeAgent/TTS`). Wired through intake, generation, finalizer, orchestrator, and API startup (`configure_tts_logging`). TTS DB failures emit via `tts_pipeline/persistence/session.py`. Terraform: `infra/terraform/tts_cloudwatch.tf` (dashboard + alarms including finalization metrics and review-required composite job-failure alarm).

---

## 14) Phase 13 — security and config

### Goal

Ensure the TTS plane is production-safe.

### Checklist

- [ ] Store ElevenLabs API key in Secrets Manager.
- [x] Restrict IAM to only required S3 paths and DB tables.
- [ ] Restrict access to TTS job endpoints.
- [x] Restrict voice profile configuration to approved inputs.
- [ ] Redact secrets from logs.
- [ ] Protect request payloads where needed.
- [x] Set encryption at rest for storage.
- [ ] Define retention policy for manifests and debug data.

### Exit criteria

- [ ] The TTS plane follows least privilege.
- [ ] Secret handling is production-safe.

---

## 15) Phase 14 — testing

### Goal

Verify the plane before production use.

### Checklist

- [x] Unit test transcript ingestion.
- [x] Unit test chunk planning.
- [x] Unit test voice policy resolution.
- [x] Unit test ElevenLabs request building.
- [x] Unit test S3 persistence.
- [x] Unit test manifest assembly.
- [ ] Integration test one full job.
- [x] Integration test chunk retry.
- [x] Integration test duplicate retry.
- [x] Integration test partial failure.
- [ ] Integration test final manifest creation.
- [x] Integration test observability hooks.

### Exit criteria

- [ ] The TTS plane works end to end in staging.
- [ ] Failures behave as expected.

**Notes:** `tests/tts/` covers unit and behavioral tests (61 tests). Full-job verification is via local smoke scripts, not yet an automated staging integration suite.

---

## 16) Phase 15 — staged rollout

### Goal

Launch safely and incrementally.

### Checklist

- [x] Deploy schema migrations.
- [x] Deploy S3 and IAM.
- [x] Deploy TTS job intake.
- [x] Deploy chunk planner.
- [x] Deploy ElevenLabs client.
- [x] Deploy orchestrator.
- [x] Run one internal job.
- [ ] Verify chunks and manifest.
- [ ] Verify logs and alarms.
- [ ] Verify cost and duration.
- [ ] Increase usage gradually.
- [ ] Keep rollback path available.

### Exit criteria

- [ ] A single transcript can be rendered to audio reliably.
- [ ] The workflow is stable enough for repeated use.

**Notes:** Migration `002`, S3 bucket, TTS worker Lambda (`creative-agent-dev-tts-worker`), SQS queue (`creative-agent-dev-tts-audio`), and `POST /audio-jobs` are deployed. Worker runs the full orchestrator via SQS (mirrors Agent 2 pattern). Step Functions ASL remains optional future work.

---

## 17) Definition of done

The TTS plane is done when:

- [x] an `ELEVENLABS_ENHANCED` transcript can become an audio job,
- [x] the job is chunked,
- [x] ElevenLabs generates audio,
- [x] audio is stored in S3,
- [x] metadata is stored in Aurora,
- [x] the manifest is complete,
- [x] retries are safe,
- [x] and operators can observe the whole process.

---

## 18) Important implementation invariants

- [x] Transcript pipeline remains unchanged.
- [x] TTS plane reads only enhanced transcript versions.
- [x] S3 stores binary audio; Aurora stores metadata.
- [x] Chunk generation is idempotent.
- [x] Voice policy is controlled.
- [x] Continuity context is preserved.
- [x] Model consistency is maintained across chunks.
- [x] Manual operator replay is possible.
- [x] The repo remains a monorepo with clean segment boundaries.

---

## 19) Final note

Phases 0–12 are complete in code and locally verified. **Next implementation step: Phase 13 — security and config** (Secrets Manager, production IAM hardening).

Do not reopen the transcript pipeline.
Do not collapse the new plane into the old one.
Keep the boundary crisp, because the system now has a solid upstream transcript foundation and is ready for audio generation.
