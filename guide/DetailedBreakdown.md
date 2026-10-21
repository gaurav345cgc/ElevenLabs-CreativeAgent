# Transcript Creation and ElevenLabs Enhancement Plane

## Purpose

This document defines the architecture, responsibilities, data model, workflow, and operational guidance for the in-house production subsystem that creates narration transcripts and then enhances them for ElevenLabs text-to-speech. It is intended to give implementation agents and engineers a complete working context before building any code.

The subsystem is deliberately split into two isolated agents:

1. **Pattern Transcript Composer** — creates the base transcript from the pattern library and content taxonomy.
2. **ElevenLabs Script Doctor** — rewrites the base transcript into a TTS-optimized narration package suitable for direct use with ElevenLabs.

This split is intentional because content correctness and speakability are different concerns. The first agent is responsible for therapeutic fit, pattern fidelity, and content structure. The second agent is responsible for prosody, readability for voice synthesis, chunking, punctuation shaping, and pronunciation normalization. The pattern index explicitly defines how new scripts should be assembled, while the examples file explicitly states that reference transcripts should be used for tone and language guidance during writing.[cite:997][cite:996]

## System Philosophy

### Core principles

- The subsystem is **production-facing and in-house**.
- The subsystem should be **modular and isolated**, even though the end-to-end user experience feels simple.
- Agent 1 and Agent 2 must be independently deployable and independently retryable.
- The database is the **system of record**, but not the primary handoff mechanism between agents.
- Asynchronous handoff should use AWS-native event-driven transport so retries, burst handling, and failure isolation are operationally clean.[cite:1014][cite:1033][cite:1037]

### Why two agents exist

The pattern library provides the structural blueprint for building a new meditation in ordered stages: opening, settling, body work, breath work, mind/heart work, and closing.[cite:997] The examples file explains that the examples should be used to capture phrasing, pace, and emotional register for the chosen context.[cite:996] That makes Agent 1 fundamentally a structured composition engine.

The second pass exists because ElevenLabs performance quality depends heavily on sentence construction, punctuation, chunking, continuity context, and text normalization for long-form narration. ElevenLabs documentation recommends splitting long text into segments and using continuity context such as `previous_text` and `next_text` when generating across chunks.[cite:998][cite:1000][cite:1012]

## What We Are Building

The system creates one canonical transcript entity that evolves through two production states:

1. **Base transcript created** from the internal pattern and examples knowledge base.
2. **Enhanced transcript created** from the base transcript using a TTS writer's pass for ElevenLabs.

The final output of this subsystem is not audio and not video. The final output is a **high-quality enhanced narration package** that can be passed directly into ElevenLabs manually or through API automation.

## High-Level Architecture

```text
                 ┌──────────────────────────────────────┐
                 │         Internal Product UI          │
                 │ brief, content selection, status     │
                 └─────────────────┬────────────────────┘
                                   │
                                   v
                 ┌──────────────────────────────────────┐
                 │      Intake API / Orchestration      │
                 │ validate request, create job         │
                 └─────────────────┬────────────────────┘
                                   │
                                   v
                 ┌──────────────────────────────────────┐
                 │ Lambda 1: Pattern Transcript Composer│
                 │ creates base transcript              │
                 └─────────────────┬────────────────────┘
                                   │
                      write transcript + version to DB
                                   │
                                   v
                 ┌──────────────────────────────────────┐
                 │ Aurora PostgreSQL                    │
                 │ status = PENDING_ENHANCEMENT         │
                 └─────────────────┬────────────────────┘
                                   │
                       publish transcript_id to SQS
                                   │
                                   v
                 ┌──────────────────────────────────────┐
                 │ SQS: transcript-enhancement queue    │
                 │ retries, DLQ, burst buffering        │
                 └─────────────────┬────────────────────┘
                                   │
                                   v
                 ┌──────────────────────────────────────┐
                 │ Lambda 2: ElevenLabs Script Doctor   │
                 │ creates enhanced transcript          │
                 └─────────────────┬────────────────────┘
                                   │
                     write enhanced version to same DB
                                   │
                                   v
                 ┌──────────────────────────────────────┐
                 │ Aurora PostgreSQL                    │
                 │ status = ENHANCED                    │
                 └──────────────────────────────────────┘
```

This architecture keeps the two agents isolated while using Aurora as the source of truth and SQS as the asynchronous handoff layer. AWS event-driven guidance and common SQS-based patterns support this decoupled model for resilience, retry handling, and backlog control.[cite:1014][cite:1033][cite:1037]

## Why Not Use the Database as the Queue

The database should store authoritative records, status, audit history, and transcript versions. It should not be the primary mechanism that Agent 2 polls for work unless the team deliberately accepts the operational burden of building queue semantics inside SQL.

A DB-polling design requires custom handling for:

- polling cadence,
- row leasing,
- duplicate pickup prevention,
- stuck jobs,
- retry counts,
- dead-letter behavior,
- backlog observability,
- and consumer concurrency.

Using SQS between Lambda 1 and Lambda 2 offloads those concerns to managed infrastructure and is a more production-grade architecture for an in-house system.[cite:1033][cite:1037]

## Agent Definitions

## Agent 1 — Pattern Transcript Composer

### Responsibility

Agent 1 creates the initial transcript from the meditation taxonomy, pattern index, and examples library. It is responsible for content correctness, tone fit, structural fidelity, and version registration.

### Inputs

- generation
- wound or wound_id
- stage
- pillar
- principles if explicitly selected
- target duration
- content type
- title hint or campaign brief

### Internal knowledge sources

- `meditation_patterns_index` defines the script assembly flow and the applicable pattern families for specific wounds, stages, and contexts.[cite:997]
- `meditation_patterns_examples` provides tone, pace, and emotional-register reference for those patterns and contexts.[cite:996]

### Output

Agent 1 should output a **base transcript**, not a TTS-optimized transcript.

Recommended output fields:

- transcript title
- transcript text
- sectioned script
- selected pattern plan
- estimated duration
- generation / wound / stage metadata
- status = `PENDING_ENHANCEMENT`

### Required behavior

- Follow the six-stage composition flow defined in the pattern index.[cite:997]
- Use examples as style reference, not content to copy.[cite:996]
- Preserve wound-specific and generation-specific emotional register.[cite:997][cite:996]
- Store the result immediately in the database as the first version of the transcript.

## Agent 2 — ElevenLabs Script Doctor

### Responsibility

Agent 2 takes the stored base transcript and rewrites it into an ElevenLabs-ready narration package. Its job is to improve speakability without damaging the meaning, structure, or emotional register established by Agent 1.

### Inputs

- transcript_id
- transcript version id for base transcript
- model target, for example `eleven_multilingual_v2` or `eleven_v3`
- output mode (`plain_paste`, `api_chunked`, or `v3_tagged`)

### Output

Agent 2 creates a second transcript version of kind `ELEVENLABS_ENHANCED` and updates the transcript status to `ENHANCED` after a successful commit.

Recommended output artifacts:

- enhanced full script
- beat-grouped script
- chunked script for API synthesis
- voice direction notes
- pronunciation notes
- optional audio tags for v3
- estimated duration per chunk

### Required behavior

The ElevenLabs pass should:

- remove fillers, false starts, repetitions, and transcript debris,
- convert fragments into complete conversational sentences,
- keep sentence rhythm suitable for speech,
- shape delivery with punctuation,
- normalize numbers, acronyms, and pronunciation-sensitive terms,
- split long narration into chunks,
- and optionally prepare continuity context for API generation using `previous_text` and `next_text` or request stitching patterns.[cite:998][cite:1000][cite:1012]

### Why this pass is separate

ElevenLabs supports advanced continuity handling for long text and also supports audio tags for expressive generation in Eleven v3.[cite:998][cite:1000][cite:1001][cite:1005] Those concerns belong in a separate enhancement stage rather than inside the transcript composition stage.

## Detailed Workflow

### Phase 1 — Intake

1. Internal user or system submits a content brief.
2. Intake API validates required taxonomy fields.
3. Intake API creates a transcript job record or directly invokes Lambda 1.

### Phase 2 — Base transcript creation

1. Lambda 1 receives the brief.
2. Lambda 1 selects pattern families using the pattern index guidance.[cite:997]
3. Lambda 1 writes the transcript in the correct tone using the examples file for phrasing and emotional register.[cite:996]
4. Lambda 1 inserts a transcript record if it does not exist.
5. Lambda 1 inserts a `RAW_PATTERN` transcript version.
6. Lambda 1 updates transcript status to `PENDING_ENHANCEMENT`.
7. Lambda 1 commits the transaction.
8. Lambda 1 publishes a message to the transcript-enhancement queue.

### Phase 3 — TTS enhancement

1. SQS delivers the transcript ID to Lambda 2.
2. Lambda 2 reads the transcript and latest raw version.
3. Lambda 2 attempts to atomically move status from `PENDING_ENHANCEMENT` to `ENHANCING`.
4. Lambda 2 performs the ElevenLabs writer's pass.
5. Lambda 2 inserts an `ELEVENLABS_ENHANCED` transcript version.
6. Lambda 2 updates transcript status to `ENHANCED` and sets `current_version_id`.
7. Lambda 2 commits the transaction.
8. Optional downstream event is emitted, such as `TRANSCRIPT_ENHANCED`.

### Phase 4 — Consumption

The enhanced transcript can then be:

- copied manually into ElevenLabs,
- used by an automated TTS job,
- or passed into a later video or audio assembly pipeline.

## AWS Services

| Layer | Technology | Purpose |
|---|---|---|
| Entry/API | API Gateway + FastAPI or Lambda | Accept job requests and fetch status |
| Agent 1 | AWS Lambda | Generate base transcript from pattern system |
| Persistence | Aurora PostgreSQL | Store transcript entities, versions, statuses |
| Async handoff | Amazon SQS + DLQ | Reliable decoupling between Agent 1 and Agent 2 |
| Agent 2 | AWS Lambda | Perform ElevenLabs enhancement rewrite |
| Secrets | AWS Secrets Manager | Database credentials and API keys |
| Observability | CloudWatch | Logs, alarms, metrics |
| Optional connection management | RDS Proxy | Protect Aurora from Lambda connection spikes |

Using Lambda with Aurora in event-driven processing is a valid AWS pattern, and SQS is well-suited for decoupled asynchronous workflows with retries and burst buffering.[cite:1014][cite:1033][cite:1037]

## Data Model

The system should not overwrite transcript text in place. It should store immutable versions under one transcript entity.

### Recommended tables

```sql
CREATE TABLE transcript (
    id UUID PRIMARY KEY,
    asset_id UUID,
    tenant_id UUID NOT NULL,
    content_type TEXT NOT NULL,
    generation_code TEXT,
    wound_id TEXT,
    stage_no INT,
    pillar_code TEXT,
    status TEXT NOT NULL,
    current_version_id UUID,
    enhancement_attempt_count INT NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE transcript_version (
    id UUID PRIMARY KEY,
    transcript_id UUID NOT NULL REFERENCES transcript(id),
    version_kind TEXT NOT NULL,
    content_text TEXT NOT NULL,
    content_json JSONB,
    created_by_agent TEXT NOT NULL,
    metadata_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE transcript_job_event (
    id UUID PRIMARY KEY,
    transcript_id UUID NOT NULL REFERENCES transcript(id),
    event_type TEXT NOT NULL,
    event_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL
);
```

### Recommended status enum values

- `CREATED`
- `PENDING_ENHANCEMENT`
- `ENHANCING`
- `ENHANCED`
- `FAILED_ENHANCEMENT`
- `REVIEW_REQUIRED`

### Recommended version kinds

- `RAW_PATTERN`
- `ELEVENLABS_ENHANCED`
- `ELEVENLABS_TAGGED` (optional future)
- `APPROVED_FINAL` (optional future)

## Message Contract Between Lambdas

The queue message should stay small and carry only identifiers and routing metadata.

Example:

```json
{
  "transcript_id": "uuid",
  "tenant_id": "uuid",
  "raw_version_id": "uuid",
  "requested_output_mode": "plain_paste",
  "voice_model": "eleven_multilingual_v2",
  "idempotency_key": "transcript-id:raw-version-id:enhancement-v1"
}
```

This keeps the handoff compact and avoids passing large text blobs through transport unnecessarily.

## Agent 1 Logic Model

### Selection flow

1. Validate the brief.
2. Select the correct opening pattern.
3. Select settling pattern.
4. Select body work pattern.
5. Select breath pattern.
6. Select mind/heart pattern.
7. Select closing pattern.[cite:997]
8. Pull nearest examples for emotional register and tone.[cite:996]
9. Generate original script.
10. Estimate duration.
11. Save raw transcript.

### Example pattern chain

A possible transcript plan could be:

- opening = `guidedmeditationintro`
- settling = `groundingsettlingposture`
- body = `softeningsettlingawareness`
- breath = `breathattention`
- mind_heart = `mindreframingoneness`
- closing = `closingtransition`[cite:997]

## Agent 2 Logic Model

### Rewrite rules

Agent 2 should apply deterministic rewrite rules before any optional voice-specific tuning.

#### Structural cleanup

- Remove filler words.
- Remove duplicate starts.
- Remove transcript artifacts.
- Replace sentence fragments with complete spoken sentences.

#### Ear-first rewrite

- Prefer one idea per sentence.
- Prefer short or medium sentence length.
- Mix sentence length for rhythm.
- Break dense prose into short beats.

#### Punctuation control

- Use periods for clear rests.
- Use commas for micro-pauses.
- Use dashes and colons sparingly.
- Avoid excessive ellipses.
- Use question marks only where rising intonation is truly desired.

#### Token normalization

- Normalize numbers to the spoken form when needed.
- Normalize acronyms to the intended spoken form.
- Normalize units and spacing.
- Add pronunciation notes for unstable proper nouns or brand names.

#### Chunking

- Break long scripts into manageable synthesis chunks.
- Include continuity context for API-based synthesis using `previous_text`, `next_text`, or request stitching support.[cite:998][cite:1000][cite:1012]

#### Optional v3 tagging

- For `eleven_v3`, support light inline tag insertion.
- Do not overload the script with tags.
- Tags must align with the emotional register and the selected voice.[cite:1001][cite:1005]

## Output Modes for Agent 2

| Mode | Description | Use case |
|---|---|---|
| `plain_paste` | Clean paragraphs and beats, no API metadata | Manual paste into ElevenLabs UI |
| `api_chunked` | Chunked output with continuity fields | Automated TTS generation |
| `v3_tagged` | Chunked output plus sparse v3 audio tags | Expressive narration with Eleven v3 |

## Database Transaction Rules

### Lambda 1 transaction

1. Insert transcript if needed.
2. Insert raw transcript version.
3. Update transcript status to `PENDING_ENHANCEMENT`.
4. Commit.
5. Publish queue message.

### Lambda 2 transaction

1. Load transcript by ID.
2. Acquire safe state transition from `PENDING_ENHANCEMENT` to `ENHANCING`.
3. Generate enhancement.
4. Insert enhanced transcript version.
5. Update current version pointer and status to `ENHANCED`.
6. Commit.

This pattern ensures that no status claims success before the content is safely persisted.

## Idempotency and Retry Model

### Why idempotency matters

SQS and Lambda consumers can retry and can occasionally deliver duplicates. The consumer must therefore be safe to run more than once for the same message.[cite:1037]

### Required safeguards

- Use an idempotency key in the queue message.
- Add a uniqueness constraint on enhancement output per transcript version and enhancement type.
- Refuse to create a duplicate enhanced version for the same raw version and same enhancement strategy.
- Track `enhancement_attempt_count`.

### Failure handling

- Transient failure: message retry through SQS.
- Repeated failure: move to DLQ.
- Persistent quality problem: mark transcript `REVIEW_REQUIRED`.
- Unexpected DB conflict: log and retry safely.

## Observability

The system should expose clear production metrics.

### Key metrics

- number of transcripts created,
- number pending enhancement,
- enhancement latency,
- enhancement failure rate,
- queue depth,
- age of oldest queue message,
- Lambda duration and error count,
- Aurora write errors,
- number of items in DLQ.

These are standard and important metrics for asynchronous Lambda plus SQS systems because they reveal stuck consumers, backlog growth, and downstream pressure.[cite:1037]

## Security and Production Controls

### Security

- Store database credentials in Secrets Manager.
- Scope IAM roles per Lambda.
- Use least privilege for SQS and database access.
- Protect PII and tenant context in logs.

### Production resilience

- Configure Lambda reserved concurrency for Agent 2 to protect Aurora and any downstream TTS provider.
- Consider RDS Proxy if Lambda concurrency will grow or connections become spiky.
- Configure SQS DLQ and alarm on non-empty DLQ.
- Use CloudWatch alarms for queue age, Lambda errors, and enhancement failure spikes.

## Design Decisions

### Decision 1 — Two Lambdas instead of one

The two responsibilities are intentionally separated because transcript composition and TTS optimization have different failure modes, different logic, and different future evolution paths. This also makes retries cleaner and preserves isolation between content generation and speech optimization.[cite:997][cite:996][cite:998]

### Decision 2 — Aurora as source of truth, SQS as handoff

Aurora stores the canonical state and version history. SQS carries the work signal between stages. This is the recommended production compromise between correctness and reliability.[cite:1014][cite:1033][cite:1037]

### Decision 3 — Versioned transcript storage

The system stores both raw and enhanced versions instead of overwriting the same text field. This enables rollback, QA comparison, human review, and future support for multiple enhancement strategies.

### Decision 4 — Enhancement is content-preserving

Agent 2 should improve speakability, not change the therapeutic intent. Its job is to make the transcript ElevenLabs-worthy, not to reinterpret the core content.

## Out of Scope for This Phase

The following are not part of this subsystem yet:

- audio generation,
- voice cloning,
- final ElevenLabs API execution,
- subtitle timecoding,
- video rendering,
- visual scene planning,
- publishing workflows,
- creative content beyond transcript and TTS enhancement.

Those can be added as downstream planes or later stages after the transcript and enhancement pipeline is stable.

## Implementation Guidance for Cursor Agent

When implementing this subsystem, the codebase should be organized around strict boundaries:

- `transcript_composer/` for Agent 1 logic,
- `tts_enhancer/` for Agent 2 logic,
- `models/` for shared DTOs and persistence models,
- `repositories/` for DB access,
- `queues/` for SQS message contracts,
- `workflows/` for orchestration and state transitions,
- `observability/` for metrics and logging.

Cursor should preserve these invariants:

1. Never let Agent 2 synthesize from an unstored in-memory transcript.
2. Never let Agent 2 overwrite the raw transcript.
3. Never use database polling as the default worker trigger.
4. Never couple transcript generation and TTS enhancement in the same Lambda handler.
5. Always persist status changes transactionally.
6. Always make Lambda 2 idempotent.
7. Always keep queue messages small and identifier-based.
8. Always preserve the emotional register selected by Agent 1.

## Final Summary

This subsystem is a two-agent, event-driven transcript pipeline for in-house production use. Agent 1 composes the transcript from the pattern taxonomy and examples corpus. Agent 2 rewrites that transcript into a form optimized for ElevenLabs narration. Aurora stores the canonical transcript entity and immutable transcript versions. SQS provides the asynchronous handoff between Lambdas. This architecture keeps the workflow isolated, debuggable, retryable, and ready for later expansion into TTS execution and full video generation.[cite:997][cite:996][cite:1014][cite:1033][cite:998]
