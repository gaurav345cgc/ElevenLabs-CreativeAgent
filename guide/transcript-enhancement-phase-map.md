# Transcript Enhancement Phase Map (Complete)

## Purpose

This document defines the phased build plan for the **transcript enhancement plane**: base transcript from the meditation pattern system, then ElevenLabs-ready enhancement via Agent 2. Phases 0–10 are **complete and deployed**; phases 11–15 remain optional hardening.

**Next downstream work:** the **TTS orchestration plane** (transcript → ElevenLabs audio → S3). Use [`tts-plane-phase-map.md`](tts-plane-phase-map.md) and [`architecture-and-tts-plane.md`](architecture-and-tts-plane.md). Do not reopen or collapse into the transcript pipeline.

The subsystem has two isolated agents:

1. **Pattern Transcript Composer** — creates the initial transcript from the pattern index and examples corpus.[cite:997][cite:996]
2. **ElevenLabs Script Doctor** — rewrites that transcript into an ElevenLabs-ready narration package, including chunking and continuity-aware formatting for long-form synthesis.[cite:998][cite:1000][cite:1012]

The architecture should remain event-driven: Agent 1 writes the canonical transcript and raw version to Aurora PostgreSQL, marks it `PENDING_ENHANCEMENT`, and hands off work through SQS; Agent 2 consumes that work, creates the enhanced version, and marks the transcript `ENHANCED`.[cite:1014][cite:1033][cite:1037]

---

## Build principles

- Build the system in **layers**, not all at once.
- Complete the persistence and workflow contract before prompt tuning.
- Keep Agent 1 and Agent 2 separately deployable.
- Use Aurora as the source of truth and SQS as the asynchronous handoff layer.[cite:1014][cite:1033]
- Store immutable transcript versions instead of overwriting transcript text.
- Make Agent 2 idempotent because queue consumers can retry and duplicate deliveries are possible in production.[cite:1037]

---

## Phase 0 — Foundation and alignment

### Objective

Define the product boundary, finalize core invariants, and prepare the implementation repository.

### Deliverables

- [x] Approved architecture definition — [`AGENTS.md`](AGENTS.md), [`DetailedBreakdown.md`](DetailedBreakdown.md)
- [x] Approved status model — `CREATED` → `PENDING_ENHANCEMENT` → `ENHANCING` → `ENHANCED` | `FAILED_ENHANCEMENT` | `REVIEW_REQUIRED`
- [x] Approved versioning model — immutable `transcript_version` kinds: `RAW_PATTERN`, `ELEVENLABS_ENHANCED` (+ future kinds)
- [x] Approved queue handoff model — identifier-only SQS message + `idempotency_key` ([`AGENTS.md`](AGENTS.md#sqs-message-contract))
- [x] Repository structure — see [`phase-0-foundation.md`](phase-0-foundation.md)
- [x] Environment strategy for dev, staging, production — [`phase-0-foundation.md`](phase-0-foundation.md#environment-strategy)

### Checklist

- [x] Confirm the subsystem boundary: this phase ends at **enhanced transcript**, not audio or video.
- [x] Confirm the two-agent split is final: `Pattern Transcript Composer` and `ElevenLabs Script Doctor`.[cite:997][cite:998]
- [x] Confirm Aurora PostgreSQL is the system of record.
- [x] Confirm SQS is the handoff mechanism between agents, not DB polling.[cite:1033][cite:1037]
- [x] Confirm transcript storage is versioned, not overwrite-in-place.
- [x] Confirm the initial output modes required for Agent 2: `plain_paste` first, `api_chunked` second, `v3_tagged` later.[cite:1001][cite:1005]
- [x] Define repository modules: `api`, `transcript_composer`, `tts_enhancer`, `db`, `queues`, `models`, `observability`, `infra`.
- [x] Decide programming language and framework for Lambda handlers — **Python 3.12 + FastAPI** ([`phase-0-foundation.md`](phase-0-foundation.md#technology-decisions))
- [x] Define environment variable naming conventions — `CREATIVE_AGENT_*` ([`.env.example`](../.env.example))
- [x] Define logging format and trace correlation strategy — structured JSON + `correlation_id` ([`phase-0-foundation.md`](phase-0-foundation.md#logging-and-trace-correlation))
- [x] Define tenant and auth assumptions, even if internal-only — internal API key/IAM + `tenant_id` ([`phase-0-foundation.md`](phase-0-foundation.md#tenant-and-auth-assumptions))

### Exit criteria

- [x] Core architecture and build order approved.
- [x] Repository skeleton created.
- [x] No unresolved architectural ambiguity before schema work begins.

---

## Phase 1 — Data model and schema

### Objective

Create the canonical database schema that all other phases depend on.

### Deliverables

- [x] Aurora schema migrations — [`db/migrations/versions/001_initial_schema.py`](../db/migrations/versions/001_initial_schema.py)
- [x] Transcript and version tables
- [x] Status enum or constrained status model — [`models/enums.py`](../models/enums.py) + DB `CHECK`
- [x] Indexes and uniqueness rules
- [x] Audit/event table

### Checklist

- [x] Create `transcript` table.
- [x] Create `transcript_version` table.
- [x] Create `transcript_job_event` or equivalent audit table.
- [x] Add `current_version_id` pointer on transcript entity.
- [x] Add `enhancement_attempt_count` and `last_error` fields.
- [x] Add tenant and asset relationship fields as needed.
- [x] Add status constraint for:
  - [x] `CREATED`
  - [x] `PENDING_ENHANCEMENT`
  - [x] `ENHANCING`
  - [x] `ENHANCED`
  - [x] `FAILED_ENHANCEMENT`
  - [x] `REVIEW_REQUIRED`
- [x] Add version kind constraint for:
  - [x] `RAW_PATTERN`
  - [x] `ELEVENLABS_ENHANCED`
  - [x] `ELEVENLABS_TAGGED` (future)
  - [x] `APPROVED_FINAL` (future)
- [x] Add uniqueness constraints to prevent duplicate enhanced versions for the same raw version and enhancement mode.
- [x] Add indexes for:
  - [x] `transcript.status`
  - [x] `transcript.tenant_id`
  - [x] `transcript.current_version_id`
  - [x] `transcript_version.transcript_id`
  - [x] `transcript_version.version_kind`
- [x] Add migration rollback strategy — [`db/README.md`](../db/README.md)
- [x] Test migrations in a local or staging database — applied on Aurora dev (`001` at head)

### Exit criteria

- [x] Schema deployed and validated — `alembic current` → `001 (head)` on `creative-agent-dev-v1`
- [x] Core tables and constraints available for application development

---

## Phase 2 — Domain contracts and shared models

### Objective

Define the internal contracts used by API, Agent 1, Agent 2, and the queue.

### Deliverables

- [x] DTOs / schemas for request and response payloads — [`models/`](../models/)
- [x] Shared transcript state model — [`models/records.py`](../models/records.py), [`models/enums.py`](../models/enums.py)
- [x] Shared queue message contract — [`models/messages.py`](../models/messages.py)
- [x] Validation layer — [`models/validation.py`](../models/validation.py)

### Checklist

- [x] Define `CreateTranscriptRequest` schema.
- [x] Define `TranscriptRecord` model.
- [x] Define `TranscriptVersionRecord` model.
- [x] Define `EnhancementJobMessage` schema.
- [x] Define `Agent1Output` schema.
- [x] Define `Agent2Output` schema.
- [x] Define `ErrorEnvelope` model.
- [x] Define consistent timestamp and UUID conventions — [`models/common.py`](../models/common.py)
- [x] Define metadata JSON structure for:
  - [x] selected patterns
  - [x] generation/wound/stage/pillar context
  - [x] duration estimate
  - [x] enhancement mode
  - [x] voice model target
- [x] Define validation rules for invalid combinations of wound, stage, and pattern usage based on the pattern index.[cite:997] — seed rules in [`models/validation.py`](../models/validation.py); full index in Phase 5

### Exit criteria

- [x] All internal interfaces typed and versioned.
- [x] No ad hoc payloads between system components.

---

## Phase 3 — Infrastructure baseline

### Objective

Provision the minimum AWS infrastructure for a production-safe first version.

### Deliverables

- [x] Aurora PostgreSQL instance or cluster — **dev cluster exists** (`creative-agent-dev-v1`)
- [x] SQS queue and DLQ — deployed dev (`creative-agent-dev-enhancement`)
- [x] Lambda execution roles — `creative-agent-dev-composer-lambda`, `creative-agent-dev-enhancer-lambda`
- [x] Secrets Manager entries — `creative-agent-dev/database`, `creative-agent-dev/model-provider`
- [x] CloudWatch log groups and alarms — deployed dev
- [x] Optional RDS Proxy — **decision: off for dev**; enable in production tfvars

### Checklist

- [x] Provision Aurora PostgreSQL environment.
- [x] Provision application database and schema owner role — `creative_agent` DB + migrations applied.
- [x] Provision SQS main queue for enhancement jobs.
- [x] Provision SQS dead-letter queue.
- [x] Set redrive policy on main queue.
- [x] Create Lambda role for Agent 1.
- [x] Create Lambda role for Agent 2.
- [x] Restrict IAM permissions to least privilege — scoped inline policies in Terraform.
- [x] Store DB credentials in Secrets Manager.
- [x] Store any model provider secrets in Secrets Manager — secret created (add API key version when needed).
- [x] Create CloudWatch log groups.
- [x] Add initial alarms for:
  - [x] Lambda errors
  - [x] queue depth
  - [x] age of oldest message
  - [x] DLQ non-empty
- [x] Decide whether RDS Proxy is required for expected Lambda concurrency.[cite:1014] — **not for dev**
- [ ] Create staging and production variants of all resources — tfvars examples ready; deploy when needed

### Exit criteria

- [x] Infrastructure exists and applications can connect securely — `terraform apply` complete (19 resources)
- [x] Queue and database are ready for integration testing

---

## Phase 4 — Persistence layer

### Objective

Build the database access layer and transactional operations.

### Deliverables

- [x] Transcript repository — [`db/repositories/transcript_repository.py`](../db/repositories/transcript_repository.py)
- [x] Transcript version repository — same module (`insert_transcript_version`, `find_enhanced_version`)
- [x] State transition helpers — [`db/state.py`](../db/state.py)
- [x] DB transaction wrappers — [`db/session.py`](../db/session.py)

### Checklist

- [x] Build `create_transcript()` repository method.
- [x] Build `insert_transcript_version()` method.
- [x] Build `update_transcript_status()` method.
- [x] Build `set_current_version()` method.
- [x] Build `record_job_event()` method.
- [x] Build `load_transcript_with_versions()` method.
- [x] Build `claim_for_enhancement()` method with atomic state transition from `PENDING_ENHANCEMENT` to `ENHANCING`.
- [x] Build `mark_enhancement_failed()` method.
- [x] Build transaction helper utilities.
- [x] Add retry-safe DB write patterns.
- [x] Add structured logging around transactions.
- [x] Add unit tests for state transitions and duplicate-protection logic.

### Exit criteria

- [x] Database writes and reads are reliable and transaction-safe.
- [x] No business logic writes directly to SQL without repository abstractions.

---

## Phase 5 — Pattern knowledge ingestion

### Objective

Make the pattern index and examples corpus usable by Agent 1 in a deterministic and queryable way.

### Deliverables

- [x] Parsed pattern index representation — [`transcript_composer/data/meditation_patterns_index.json`](../transcript_composer/data/meditation_patterns_index.json)
- [x] Parsed examples representation — [`transcript_composer/data/meditation_patterns_examples.json`](../transcript_composer/data/meditation_patterns_examples.json)
- [x] Pattern selection service — [`transcript_composer/knowledge/pattern_selector.py`](../transcript_composer/knowledge/pattern_selector.py)
- [x] Example retrieval service — [`transcript_composer/knowledge/example_retriever.py`](../transcript_composer/knowledge/example_retriever.py)

### Checklist

- [x] Parse the meditation pattern index into structured data.
- [x] Parse the examples file into structured data.
- [x] Normalize fields for:
  - [x] generation
  - [x] wound_id
  - [x] stage
  - [x] pillar
  - [x] pattern family
  - [x] placement
  - [x] instruction rule
  - [x] use case
  - [x] tone notes
- [x] Build selector for pattern family by composition slot:
  - [x] opening
  - [x] settling
  - [x] body
  - [x] breath
  - [x] mind/heart
  - [x] closing
- [x] Build ranking logic for matching examples to selected context.
- [x] Add fallback behavior when an exact example match does not exist.
- [x] Store parsed assets as code constants, JSON resources, or DB reference tables — JSON in `transcript_composer/data/`
- [x] Add tests verifying the selector uses valid combinations from the pattern index.[cite:997]

### Exit criteria

- [x] Agent 1 can deterministically choose patterns and fetch contextual tone references.

---

## Phase 6 — Agent 1 implementation

### Objective

Implement the Pattern Transcript Composer end to end.

### Deliverables

- [x] Lambda 1 handler — [`transcript_composer/handler.py`](../transcript_composer/handler.py)
- [x] Composition service — [`transcript_composer/composition_service.py`](../transcript_composer/composition_service.py)
- [x] Duration estimation logic — [`transcript_composer/duration.py`](../transcript_composer/duration.py)
- [x] DB persistence integration — [`transcript_composer/persistence.py`](../transcript_composer/persistence.py)
- [x] SQS publish integration — [`queues/publisher.py`](../queues/publisher.py)

### Checklist

- [x] Implement Lambda 1 entrypoint.
- [x] Validate request payload.
- [x] Select pattern chain from pattern index.[cite:997]
- [x] Load closest example references for tone and emotional register.[cite:996]
- [x] Generate original section-by-section script.
- [x] Preserve the six-stage flow defined in the pattern index.[cite:997]
- [x] Add title generation logic.
- [x] Add estimated duration calculation.
- [x] Build `selected_pattern_plan` metadata payload.
- [x] Persist transcript record and raw version transactionally.
- [x] Set transcript status to `PENDING_ENHANCEMENT`.
- [x] Publish enhancement job message to SQS after successful commit.
- [x] Add structured logs with transcript ID and tenant ID.
- [x] Add unit tests for pattern selection and metadata output.
- [x] Add integration tests that verify DB write + queue publish behavior.

### Exit criteria

- [x] A valid content brief can produce a stored raw transcript and queue an enhancement job.

---

## Phase 7 — Queue contract and asynchronous handoff

### Objective

Stabilize the message-passing layer between Agent 1 and Agent 2.

### Deliverables

- [x] SQS message producer — `queues/publisher.py`
- [x] SQS-triggered Lambda 2 subscription — `infra/terraform/lambda.tf`
- [x] idempotency key design — `models/messages.py`, `queues/idempotency.py`
- [x] retry and DLQ policy — `infra/terraform/sqs.tf`

### Checklist

- [x] Finalize message schema fields:
  - [x] `transcript_id`
  - [x] `tenant_id`
  - [x] `raw_version_id`
  - [x] `requested_output_mode`
  - [x] `voice_model`
  - [x] `idempotency_key`
- [x] Ensure messages only contain identifiers and light metadata, not full transcript text.
- [x] Configure Lambda 2 as SQS consumer (mapping disabled until Phase 8 Lambda deploy).
- [x] Tune batch size appropriately.
- [x] Tune visibility timeout greater than max Lambda 2 runtime.[cite:1037]
- [x] Tune retry and DLQ settings.
- [x] Add correlation IDs to logs.
- [x] Add integration tests for duplicate message handling.
- [x] Add integration tests for retry and DLQ routing.

### Exit criteria

- [x] Handoff between agents is durable, observable, and retry-safe.

---

## Phase 8 — Agent 2 implementation

### Objective

Implement the ElevenLabs Script Doctor.

### Deliverables

- [x] Lambda 2 handler — `tts_enhancer/handler.py`
- [x] enhancement engine — `tts_enhancer/engine.py`
- [x] chunking engine — `tts_enhancer/rewrite/chunking.py`
- [x] punctuation and normalization layer — `tts_enhancer/rewrite/`
- [x] enhanced version persistence — `tts_enhancer/persistence.py`

### Checklist

- [x] Implement Lambda 2 entrypoint.
- [x] Load transcript and raw version from DB.
- [x] Atomically claim transcript for enhancement.
- [x] Build rewrite pipeline:
  - [x] remove disfluencies
  - [x] remove duplicate starts
  - [x] complete sentence fragments
  - [x] group into beats
  - [x] normalize punctuation
  - [x] normalize numbers and acronyms
  - [x] build voice direction notes
- [x] Implement output mode `plain_paste` first.
- [x] Implement chunking for long transcripts.
- [x] Add support for continuity context fields such as `previous_text` and `next_text` for API usage.[cite:998][cite:1000][cite:1012]
- [x] Persist enhanced transcript version transactionally.
- [x] Update status to `ENHANCED` on success.
- [x] Update status to `FAILED_ENHANCEMENT` or `REVIEW_REQUIRED` when appropriate.
- [x] Add idempotency protection so duplicate queue deliveries do not create duplicate enhanced versions.[cite:1037]
- [x] Add unit tests for sentence rewrite logic.
- [x] Add tests for chunking logic and continuity metadata.
- [x] Add integration tests that validate the full Agent 2 transaction flow.

### Exit criteria

- [x] Any valid raw transcript can be transformed into a stored ElevenLabs-ready version.

---

## Phase 9 — ElevenLabs formatting modes

### Objective

Expand Agent 2 outputs into clearly defined consumer-ready modes.

### Deliverables

- [x] `plain_paste` mode — `tts_enhancer/formats/plain_paste.py`
- [x] `api_chunked` mode — `tts_enhancer/formats/api_chunked.py`
- [x] optional `v3_tagged` mode — `tts_enhancer/formats/v3_tagged.py`

### Checklist

#### `plain_paste`
- [x] Output clean sectioned text for manual paste.
- [x] Group into short readable beats.
- [x] Include optional voice notes outside the main text.

#### `api_chunked`
- [x] Output chunk array with sequence index.
- [x] Include `previous_text` and `next_text` fields when appropriate.[cite:998][cite:1000]
- [x] Include estimated duration per chunk.
- [x] Include continuity-safe punctuation at chunk edges.

#### `v3_tagged` (later phase)
- [x] Add sparse audio tag insertion strategy.
- [x] Align tags with chosen voice characteristics.
- [x] Prevent excessive or unstable tag stacking.[cite:1001][cite:1005]
- [x] Test fallback to untagged text when quality drops.

### Exit criteria

- [x] Agent 2 supports at least one production-ready output mode and has a roadmap for the others.

---

## Phase 10 — API and internal control plane

### Objective

Expose the subsystem through internal APIs for creating jobs, fetching status, and retrieving transcript versions.

### Deliverables

- [x] create transcript endpoint — `POST /transcripts`
- [x] get transcript status endpoint — `GET /transcripts/{id}`
- [x] get transcript versions endpoint — `GET /transcripts/{id}/versions`
- [x] optional retry enhancement endpoint — `POST /transcripts/{id}/retry-enhancement`

### Checklist

- [x] Implement `POST /transcripts`.
- [x] Implement `GET /transcripts/{id}`.
- [x] Implement `GET /transcripts/{id}/versions`.
- [x] Implement optional `POST /transcripts/{id}/retry-enhancement`.
- [x] Add auth and tenant validation.
- [x] Add response schemas.
- [x] Add structured error handling.
- [ ] Add rate limiting if needed.
- [x] Add API tests.

### Exit criteria

- [x] Internal systems can create and observe transcript jobs without touching Lambdas directly.

---

## Phase 11 — Observability and operations

### Objective

Make the system operable in staging and production.

### Deliverables

- dashboards
- alarms
- structured logs
- audit events
- operational runbook

### Checklist

- [ ] Add structured logs for both Lambdas.
- [ ] Include transcript ID, version ID, tenant ID, status transition, and message ID in logs.
- [ ] Add CloudWatch dashboard for:
  - [ ] transcript counts by status
  - [ ] enhancement latency
  - [ ] queue depth
  - [ ] age of oldest message
  - [ ] Lambda errors
  - [ ] DLQ count
- [ ] Add alerts for:
  - [ ] repeated enhancement failures
  - [ ] queue backlog growth
  - [ ] DLQ non-empty
  - [ ] DB connectivity failure
- [ ] Build runbook for:
  - [ ] replaying failed enhancements
  - [ ] inspecting bad transcripts
  - [ ] clearing stuck `ENHANCING` rows
  - [ ] responding to DLQ growth
- [ ] Add audit trail entries to `transcript_job_event`.

### Exit criteria

- Operators can detect, diagnose, and recover from common failures.

---

## Phase 12 — Quality control and human review

### Objective

Add controlled review mechanisms before scaling usage.

### Deliverables

- quality checks
- review-required routing
- transcript diffing tools

### Checklist

- [ ] Define quality heuristics for Agent 2 output.
- [ ] Detect empty or near-empty enhancement outputs.
- [ ] Detect over-short or over-long enhanced outputs versus raw duration target.
- [ ] Detect broken chunk boundaries.
- [ ] Detect suspiciously unchanged raw-to-enhanced output where enhancement should have occurred.
- [ ] Build review flagging logic.
- [ ] Build transcript diff view for raw versus enhanced comparison.
- [ ] Add reviewer notes field if manual QA will exist.
- [ ] Add `REVIEW_REQUIRED` operational path.

### Exit criteria

- System can catch bad outputs before they silently flow downstream.

---

## Phase 13 — Security hardening

### Objective

Harden the subsystem for internal production use.

### Deliverables

- IAM review
- secret rotation policy
- log redaction policy
- least-privilege validation

### Checklist

- [ ] Audit IAM role permissions for both Lambdas.
- [ ] Restrict DB secret access by role.
- [ ] Restrict queue publish/consume permissions.
- [ ] Ensure logs do not leak sensitive content unnecessarily.
- [ ] Define data retention policy for transcript versions.
- [ ] Define secret rotation plan.
- [ ] Add environment-specific permission separation.
- [ ] Verify staging cannot publish into production queues.

### Exit criteria

- Infrastructure and application access patterns are production-safe.

---

## Phase 14 — Staging validation

### Objective

Run the full system in a near-production environment before launch.

### Deliverables

- staging E2E validation report
- seeded test cases
- error injection results

### Checklist

- [ ] Seed staging with representative content briefs.
- [ ] Validate multiple generation/wound/stage combinations.
- [ ] Validate raw transcript creation.
- [ ] Validate queue handoff.
- [ ] Validate enhancement success path.
- [ ] Validate retry path.
- [ ] Validate DLQ path.
- [ ] Validate duplicate SQS delivery handling.
- [ ] Validate DB reconnection behavior.
- [ ] Validate observability dashboards and alarms.
- [ ] Validate manual retrieval of enhanced transcript.
- [ ] Validate output quality for at least one transcript per major pattern family.[cite:997][cite:996]

### Exit criteria

- Staging run proves the architecture works under normal and failure conditions.

---

## Phase 15 — Production rollout

### Objective

Launch safely with limited blast radius.

### Deliverables

- production deployment
- controlled rollout plan
- rollback plan

### Checklist

- [ ] Deploy schema migrations to production.
- [ ] Deploy Lambdas and queue configuration.
- [ ] Verify secrets and IAM bindings.
- [ ] Enable dashboards and alarms.
- [ ] Run smoke test with one internal job.
- [ ] Review logs and DB writes.
- [ ] Review queue behavior.
- [ ] Confirm enhancement output quality.
- [ ] Gradually increase usage.
- [ ] Monitor backlog, failures, and latency during rollout.
- [ ] Keep rollback plan ready for disabling Lambda 2 trigger or queue publishing if needed.

### Exit criteria

- System is live and stable in production.

---

## Phase 16 — Handoff to TTS plane

### Objective

Separate the completed transcript enhancement scope from the next downstream plane: ElevenLabs audio generation.

### Status

- [x] Transcript plane boundary ends at `ENHANCED` + `ELEVENLABS_ENHANCED` version — not audio.
- [x] TTS plane boundary defined — [`architecture-and-tts-plane.md`](architecture-and-tts-plane.md)
- [x] TTS phase map and build checklist — [`tts-plane-phase-map.md`](tts-plane-phase-map.md)
- [x] TTS code lives in `tts_pipeline/` only; transcript modules remain unchanged.
- [x] Step Functions + S3 + Aurora metadata chosen for TTS orchestration (see master spec).
- [x] Begin TTS Phase 0 (boundary approval) and Phase 1 (repo scaffold).

### Out of scope for TTS plane (later waves)

- subtitle timing generation
- QA scoring of TTS outputs
- downstream video assembly integration
- human review interface for audio
- analytics on transcript enhancement quality (transcript plane concern)

### Exit criteria

- [x] The next build wave is clearly separated from the transcript-only scope.
- [ ] First TTS job completes with chunks in S3 and manifest written.

---

## Cross-phase invariants (transcript plane)

These rules apply across every transcript phase and should never be broken:

- [x] Agent 1 and Agent 2 remain separate deployable units.
- [x] Aurora remains the source of truth.
- [x] SQS remains the async handoff mechanism.
- [x] Transcript versions are immutable.
- [x] Raw transcript is never overwritten by enhanced transcript.
- [x] Lambda 2 is idempotent.
- [x] Queue messages remain small and identifier-based.
- [x] Status transitions are transactional.
- [x] Emotional register from Agent 1 is preserved during enhancement.
- [x] Enhancement improves speakability, not meaning.

**TTS plane invariants** (full checklist in [`tts-plane-phase-map.md`](tts-plane-phase-map.md) §18): read only `ELEVENLABS_ENHANCED`; S3 for audio, Aurora for metadata; voice policy-driven; chunk-level idempotency; continuity preserved across chunks.

---

## Recommended build order summary

### Transcript plane (complete)

1. Phase 0 — Foundation and alignment ✓
2. Phase 1 — Data model and schema ✓
3. Phase 2 — Domain contracts and shared models ✓
4. Phase 3 — Infrastructure baseline ✓
5. Phase 4 — Persistence layer ✓
6. Phase 5 — Pattern knowledge ingestion ✓
7. Phase 6 — Agent 1 implementation ✓
8. Phase 7 — Queue contract and handoff ✓
9. Phase 8 — Agent 2 implementation ✓
10. Phase 10 — API and internal control plane ✓

Optional hardening: phases 11–15 (observability, QA, security, staging, production rollout).

### TTS plane (next)

Follow [`tts-plane-phase-map.md`](tts-plane-phase-map.md) in order:

1. TTS Phase 0 — Boundary definition
2. TTS Phase 1 — Repo and folder additions
3. TTS Phase 2 — Data model
4. TTS Phase 3 — S3 and IAM
5. TTS Phase 4 — ElevenLabs integration layer
6. TTS Phase 5 — Voice policy
7. TTS Phase 6 — Transcript ingestion
8. TTS Phase 7 — Chunk planning
9. TTS Phase 8 — Orchestration engine
10. TTS Phase 9 — Chunk generation
11. TTS Phase 10 — Retry and idempotency
12. TTS Phase 11 — Finalization and manifest
13. TTS Phase 12 — Observability
14. TTS Phase 13 — Security and config
15. TTS Phase 14 — Testing
16. TTS Phase 15 — Staged rollout

---

## Definition of done for version 1 (transcript plane)

Version 1 is complete when all of the following are true:

- [x] A content brief can create a raw transcript using the pattern system.[cite:997][cite:996]
- [x] That transcript is stored in Aurora with version history.
- [x] The transcript is queued for enhancement through SQS.[cite:1033][cite:1037]
- [x] Agent 2 consumes the job and writes an ElevenLabs-ready enhanced version.
- [x] Status transitions are correct and transaction-safe.
- [x] Duplicate queue deliveries do not create duplicate enhanced outputs.
- [x] Failures route to retry or DLQ safely.
- [x] Operators can inspect transcript state and logs.
- [x] The enhanced transcript is usable for manual ElevenLabs input or automated chunked generation.[cite:998][cite:1000][cite:1012]

**Version 2 (TTS plane)** is defined in [`tts-plane-phase-map.md`](tts-plane-phase-map.md) §17: `ELEVENLABS_ENHANCED` → chunked ElevenLabs synthesis → S3 audio + manifest.
