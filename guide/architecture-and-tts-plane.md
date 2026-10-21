# Creative Agent — Current Architecture and Next TTS Plane

> **Authority:** Read this document before implementing any new subsystem or changing cross-cutting architecture.  
> **Transcript plane:** complete and stable — do not redesign.  
> **Next build:** `tts_pipeline/` — ElevenLabs TTS Orchestration Plane.

This document is the **Cursor-ready master architecture spec** for the project as it exists now and the next plane we are about to build.

It is written to make the boundary very clear:

- the **transcript pipeline is already built**,
- the **API/control plane is already built**,
- the **ElevenLabs TTS plane is the next major subsystem**,
- and the repo should remain a **single monorepo** with a new TTS segment folder, not a separate repo.

---

## 1) What already exists and is done

The following system is already implemented and should be treated as the stable foundation:

### Runtime architecture

- `create_and_wait.ps1` invokes the composer Lambda directly.
- Composer writes `RAW_PATTERN` to Aurora.
- Composer sets the transcript status to `PENDING_ENHANCEMENT`.
- Composer publishes a job to SQS.
- Enhancer is triggered from SQS.
- Enhancer rewrites the transcript and stores `ELEVENLABS_ENHANCED`.
- Enhancer updates the status to `ENHANCED`.
- API Lambda reads transcript status and versions.
- Secrets Manager is used by all Lambdas for secrets access.

### Existing code layout

These are already in place:

- `api/`
- `transcript_composer/`
- `tts_enhancer/`
- `db/`
- `queues/`
- `models/`
- `observability/`
- `guide/`
- `infra/`
- `scripts/`
- `tests/`

### Existing Lambda mapping

- `creative-agent-dev-composer` → `transcript_composer.handler.handler`
- `creative-agent-dev-enhancer` → `tts_enhancer.handler.handler`
- `creative-agent-dev-api` → `api.handler.handler`

### Existing product truth

The transcript system already has the right boundaries:

- Agent 1 composes from the pattern library.
- Agent 2 improves the text for TTS.
- The API reads status and versions.
- Raw transcript is never overwritten.
- Enhanced transcript is stored as a new version.

This is the correct stable base. Do **not** redesign it.

---

## 2) What is next

The next plane is the **ElevenLabs TTS Orchestration Plane**.

That plane will:

- read `ELEVENLABS_ENHANCED` transcript versions,
- create a TTS job,
- plan chunk boundaries,
- call ElevenLabs Create speech,
- store generated audio in S3,
- persist audio job/chunk metadata in Aurora,
- support retries and partial regeneration,
- and expose the final audio manifest and status.

This is **downstream** of the current transcript pipeline, not a replacement for it.

ElevenLabs Create speech supports the important controls we need for this plane:

- `voice_id`
- `model_id`
- `voice_settings`
- `pronunciation_dictionary_locators`
- `seed`
- `previous_text`
- `next_text`
- `previous_request_ids`
- `next_request_ids`
- `apply_text_normalization`
- `enable_logging`
- `output_format`

---

## 3) Repo decision

Use the **same repo**, not a separate repo.

However, add a **new top-level segment folder** for TTS.

### Recommended repo shape

```text
Creative Agent/
├── api/
├── transcript_composer/
├── tts_enhancer/
├── tts_pipeline/              # NEW
├── db/
├── queues/
├── models/
├── observability/
├── guide/
├── infra/
├── scripts/
├── tests/
├── .cursor/rules/
├── pyproject.toml
├── .env / .env.example
└── README.md
```

This is the best choice because:

- the system is one product,
- transcript and TTS share the same data lineage,
- the same DB and AWS account are used,
- deployment tooling is shared,
- and Lambda code sharing is easier inside a monorepo.

AWS Lambda packaging supports separating function logic from dependencies and using shared code organization or layers when needed.

---

## 4) Design philosophy

### Core rules

- Keep transcript creation, transcript enhancement, and TTS generation as separate planes.
- Never make the TTS plane rewrite script meaning.
- Use Aurora as the system of record.
- Use S3 for binary audio artifacts.
- Use idempotent chunk-level generation.
- Use explicit orchestration for retries and status tracking.
- Keep voice policy controlled and not fully caller-driven.

### Why this matters

The transcript plane already handles content correctness and voice-readability. The TTS plane handles audio generation, asset persistence, continuity, and request tracing. Those are distinct failure domains and should remain distinct in code and architecture.

---

## 5) Current pipeline vs next pipeline

### Current pipeline

```text
create_and_wait.ps1
  -> Agent 1 composer Lambda
  -> Aurora RAW_PATTERN
  -> status = PENDING_ENHANCEMENT
  -> SQS
  -> Agent 2 enhancer Lambda
  -> Aurora ELEVENLABS_ENHANCED
  -> status = ENHANCED
  -> API reads result
```

### Next pipeline

```text
ENHANCED transcript in Aurora
  -> TTS job created
  -> chunk planning
  -> ElevenLabs generation
  -> S3 audio artifacts
  -> Aurora audio metadata
  -> final manifest
  -> completed audio job
```

---

## 6) New segment folder

Add this folder:

```text
tts_pipeline/
├── intake/
├── orchestrator/
├── chunk_planner/
├── generator/
├── finalizer/
├── voice_policy/
└── persistence/
```

### What each folder does

- **`intake/`** — Creates TTS jobs from enhanced transcripts.
- **`orchestrator/`** — Owns Step Functions or equivalent workflow logic.
- **`chunk_planner/`** — Splits enhanced transcripts into generation chunks.
- **`generator/`** — Calls ElevenLabs and writes audio outputs.
- **`finalizer/`** — Builds manifests and marks completion.
- **`voice_policy/`** — Controls approved voice/model/output settings.
- **`persistence/`** — Writes audio job/chunk records to Aurora.

This keeps the TTS plane isolated without fragmenting the whole repo.

---

## 7) TTS plane scope

### In scope

- Read enhanced transcript version.
- Create audio job rows.
- Determine voice profile.
- Determine output format.
- Determine model.
- Chunk text for generation.
- Call ElevenLabs Create speech.
- Save audio chunks to S3.
- Save metadata to Aurora.
- Support chunk retries.
- Support partial regeneration.
- Build final manifest.
- Expose job state.

### Out of scope

- Transcript composition.
- Transcript enhancement.
- Video rendering.
- Subtitle rendering.
- Music mixing.
- Final mastering.
- Speech-to-text.
- User-facing content editing.

---

## 8) ElevenLabs request model

The TTS plane should build requests against the ElevenLabs TTS endpoint.

### Important fields

- `voice_id`
- `model_id`
- `output_format`
- `voice_settings`
- `seed`
- `apply_text_normalization`
- `enable_logging`
- `pronunciation_dictionary_locators`
- `previous_text`
- `next_text`
- `previous_request_ids`
- `next_request_ids`

### Recommended defaults for v1

- `model_id = eleven_multilingual_v2`
- `output_format = mp3_44100_128`
- `apply_text_normalization = auto`
- `enable_logging = true`

### Why

- `eleven_multilingual_v2` is the documented default and suitable for narration.
- `mp3_44100_128` is the documented default output format.
- `enable_logging = true` preserves continuity and request history support.

### Important continuity rule

If you regenerate a middle chunk:

- prefer `previous_request_ids` and `next_request_ids`,
- because ElevenLabs uses these for continuity across multi-request generation.

---

## 9) Voice policy

Do **not** allow arbitrary raw voice config from every caller.

Instead define a **voice profile layer**:

- voice profile code,
- ElevenLabs `voice_id`,
- approved `model_id`,
- approved `output_format`,
- default `voice_settings`,
- pronunciation dictionary policy,
- seed policy,
- normalization policy.

### Example profile

```json
{
  "voice_profile_code": "gentle_feminine_primary",
  "voice_id": "voice_123",
  "default_model_id": "eleven_multilingual_v2",
  "default_output_format": "mp3_44100_128",
  "default_voice_settings": {
    "stability": 0.62,
    "similarity_boost": 0.78,
    "style": 0.12,
    "use_speaker_boost": true
  },
  "default_seed": 1337
}
```

This gives consistency and safer rollout control.

---

## 10) Chunking strategy

Chunking is critical because long narration should not be sent as one giant text block without a plan.

### Preferred hierarchy

1. Use beat boundaries produced by Agent 2 if available.
2. If not available, split by paragraph.
3. If needed, split by sentence groups.
4. As a last resort, split by size while preserving meaning.

### Chunking rules

- Never split mid-sentence unless unavoidable.
- Avoid trailing fragments like “and”, “but”, “because”.
- Keep each chunk semantically coherent.
- Preserve the slow, grounded pacing expected for meditation narration.
- Prefer sequential generation for long-form meditation content.

### Continuity fields

For the first pass:

- use `previous_text`
- use `next_text`

For regen:

- use `previous_request_ids`
- use `next_request_ids`

The ElevenLabs API supports exactly this pattern.

---

## 11) Orchestration strategy

### Recommended: Step Functions

Use Step Functions Standard for the TTS plane.

### Why

- durable orchestration,
- explicit per-step retries,
- chunk-level state visibility,
- easy partial regeneration,
- better debugging,
- easier production operations.

### Suggested state flow

1. Validate input.
2. Create audio job.
3. Load enhanced transcript.
4. Plan chunks.
5. Persist chunk plan.
6. Generate chunks.
7. Store S3 audio artifacts.
8. Register metadata.
9. Finalize manifest.
10. Mark job completed.

### Alternative

A Lambda-only version is possible for very small transcripts, but Step Functions is the better production design for this use case.

---

## 12) Data model

Add new tables for the TTS plane.

### `transcript_audio_job`

Tracks one generation run.

```sql
CREATE TABLE transcript_audio_job (
    id UUID PRIMARY KEY,
    transcript_id UUID NOT NULL,
    transcript_version_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    voice_profile_code TEXT,
    voice_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    output_format TEXT NOT NULL,
    status TEXT NOT NULL,
    total_chunks INT,
    completed_chunks INT NOT NULL DEFAULT 0,
    failed_chunks INT NOT NULL DEFAULT 0,
    enable_logging BOOLEAN NOT NULL DEFAULT true,
    apply_text_normalization TEXT NOT NULL DEFAULT 'auto',
    seed INT,
    estimated_duration_ms BIGINT,
    final_asset_id UUID,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ
);
```

### `transcript_audio_chunk`

Tracks each generated chunk.

```sql
CREATE TABLE transcript_audio_chunk (
    id UUID PRIMARY KEY,
    audio_job_id UUID NOT NULL REFERENCES transcript_audio_job(id),
    transcript_id UUID NOT NULL,
    transcript_version_id UUID NOT NULL,
    chunk_index INT NOT NULL,
    status TEXT NOT NULL,
    source_text TEXT NOT NULL,
    previous_text TEXT,
    next_text TEXT,
    previous_request_ids JSONB,
    next_request_ids JSONB,
    eleven_request_id TEXT,
    output_object_key TEXT,
    output_format TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    character_count INT NOT NULL,
    estimated_duration_ms BIGINT,
    actual_duration_ms BIGINT,
    response_headers_json JSONB,
    metadata_json JSONB,
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
```

### `transcript_audio_asset`

Tracks stored audio outputs.

```sql
CREATE TABLE transcript_audio_asset (
    id UUID PRIMARY KEY,
    audio_job_id UUID NOT NULL REFERENCES transcript_audio_job(id),
    asset_kind TEXT NOT NULL,
    object_key TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    checksum TEXT,
    byte_size BIGINT,
    metadata_json JSONB,
    created_at TIMESTAMPTZ NOT NULL
);
```

### `transcript_audio_event`

Tracks workflow events.

```sql
CREATE TABLE transcript_audio_event (
    id UUID PRIMARY KEY,
    audio_job_id UUID NOT NULL REFERENCES transcript_audio_job(id),
    event_type TEXT NOT NULL,
    event_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL
);
```

---

## 13) Status model

### Job status

- `CREATED`
- `PLANNING`
- `READY`
- `GENERATING`
- `PARTIALLY_FAILED`
- `COMPLETED`
- `FAILED`
- `REVIEW_REQUIRED`

### Chunk status

- `PLANNED`
- `GENERATING`
- `COMPLETED`
- `FAILED`
- `RETRYING`
- `SKIPPED`

---

## 14) S3 layout

Store audio artifacts outside the DB.

### Suggested S3 paths

```text
s3://tts-audio/{tenant_id}/{transcript_id}/{audio_job_id}/chunks/{chunk_index}.mp3
s3://tts-audio/{tenant_id}/{transcript_id}/{audio_job_id}/final/final.mp3
s3://tts-audio/{tenant_id}/{transcript_id}/{audio_job_id}/manifest/audio_manifest.json
s3://tts-audio/{tenant_id}/{transcript_id}/{audio_job_id}/debug/request-{chunk_index}.json
```

### Stored artifacts

- audio chunks,
- merged or final asset,
- manifest,
- debug request metadata.

---

## 15) Retry and idempotency

### Retry rules

Retry automatically for:

- provider 5xx,
- network issues,
- throttling,
- transient S3 failures,
- transient Aurora failures.

Do not auto-retry forever for:

- invalid voice configuration,
- invalid output format,
- malformed chunks,
- policy violations.

### Idempotency rules

Every chunk generation must be idempotent.

If a chunk already succeeded:

- reuse existing asset metadata,
- do not create duplicate files,
- unless explicit regeneration is requested.

### Partial regeneration

If only one chunk fails:

- regenerate that chunk only,
- use surrounding request IDs when available to maintain continuity.

AWS Lambda retry and SQS retry guidance emphasizes idempotency and DLQ-based safety for asynchronous processing.

---

## 16) Observability

### Track these metrics

- jobs created,
- jobs completed,
- jobs failed,
- chunk failure rate,
- average duration,
- average provider latency,
- cost per transcript,
- regeneration rate,
- storage failures,
- DB write failures,
- Step Functions failures.

### Log fields

- `audio_job_id`
- `chunk_index`
- `transcript_id`
- `transcript_version_id`
- `voice_id`
- `model_id`
- `request_id`
- latency
- status

### Alarms

- chunk failure spike,
- job failure spike,
- queue backlog anomalies if queueing is used,
- provider error spike,
- unusual cost increase,
- DB write failures.

---

## 17) Folder additions

Add these new folders only for the TTS plane:

```text
tts_pipeline/
├── intake/
├── orchestrator/
├── chunk_planner/
├── generator/
├── finalizer/
├── voice_policy/
└── persistence/
```

### Optional shared code

If code reuse becomes heavy later, consider Lambda layers or a separate shared package. AWS Lambda layers separate dependencies from core code and share code across multiple functions.

---

## 18) What stays unchanged

Do **not** alter these as part of the TTS build:

- `api/` (transcript routes only — extend separately for audio job APIs when planned)
- `transcript_composer/`
- `tts_enhancer/`
- existing transcript DB models,
- existing SQS enhancement flow,
- existing script runner flow,
- existing build packaging for the current three Lambdas.

These are already working and should remain stable.

---

## 19) Build order for Cursor

Implement the TTS plane in this order:

1. Add schema/migrations for audio jobs and chunks.
2. Add S3 bucket structure and IAM permissions.
3. Add a TTS job intake service.
4. Add a chunk planner.
5. Add an ElevenLabs client wrapper.
6. Add audio persistence to S3.
7. Add manifest creation.
8. Add retry and idempotency control.
9. Add observability.
10. Add a controlled rollout path.

---

## 20) Final handoff narrative

The product now has two mature stages already working:

### Stage 1 — Transcript pipeline

- compose raw script,
- enhance for ElevenLabs readability,
- store versioned transcript output.

### Stage 2 — TTS pipeline

- take enhanced transcript,
- plan audio generation,
- synthesize chunks via ElevenLabs,
- store audio artifacts,
- produce final manifest.

The TTS plane is the next production subsystem. It should be documented and implemented as a separate segment in the same repo, not as a redesign of the transcript pipeline.

---

## 21) One-line decision

**Keep the same repo, add a new `tts_pipeline/` segment, and treat the transcript system as completed upstream infrastructure.**
