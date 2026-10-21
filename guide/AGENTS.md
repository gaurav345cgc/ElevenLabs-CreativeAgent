# Creative Agent — Project Context

> **Master architecture (read first):** [`architecture-and-tts-plane.md`](architecture-and-tts-plane.md)  
> Full specification: [`DetailedBreakdown.md`](DetailedBreakdown.md)  
> Build checklist (transcript, complete): [`transcript-enhancement-phase-map.md`](transcript-enhancement-phase-map.md)  
> Build checklist (TTS plane, next): [`tts-plane-phase-map.md`](tts-plane-phase-map.md)

## What We Are Building

An **in-house, production-facing transcript pipeline** for meditation narration. It produces a high-quality **ElevenLabs-ready narration package** — not audio, not video.

Two isolated agents run in sequence:

| Agent | Name | Responsibility |
|-------|------|----------------|
| **Agent 1** | Pattern Transcript Composer | Compose base transcript from pattern library + examples (therapeutic fit, structure, tone) |
| **Agent 2** | ElevenLabs Script Doctor | Rewrite base transcript for TTS speakability (prosody, chunking, punctuation, pronunciation) |

**Why two agents:** Content correctness and speakability are different concerns with different failure modes. They must be independently deployable and retryable.

## Architecture (Non-Negotiable)

```
Internal UI → Intake API → Lambda 1 (Composer)
                              ↓ write RAW_PATTERN version
                         Aurora PostgreSQL (status = PENDING_ENHANCEMENT)
                              ↓ publish transcript_id
                         SQS (+ DLQ)
                              ↓
                         Lambda 2 (Script Doctor)
                              ↓ write ELEVENLABS_ENHANCED version
                         Aurora PostgreSQL (status = ENHANCED)
```

- **Aurora PostgreSQL** = system of record (entities, versions, status, audit)
- **SQS** = async handoff between agents (not DB polling)
- **Queue messages** = small, identifier-only (no large text blobs)

## Core Invariants

1. Never let Agent 2 synthesize from an unstored in-memory transcript.
2. Never let Agent 2 overwrite the raw transcript.
3. Never use database polling as the default worker trigger.
4. Never couple transcript generation and TTS enhancement in the same Lambda handler.
5. Always persist status changes transactionally.
6. Always make Lambda 2 idempotent.
7. Always keep queue messages small and identifier-based.
8. Always preserve the emotional register selected by Agent 1.
9. Agent 2 improves speakability — it does **not** reinterpret therapeutic intent.

## Agent 1 — Pattern Transcript Composer

### Inputs
`generation`, `wound`/`wound_id`, `stage`, `pillar`, `principles` (optional), `target_duration`, `content_type`, `title_hint`/brief

### Knowledge sources
- `meditation_patterns_index` — six-stage assembly flow (opening → settling → body → breath → mind/heart → closing)
- `meditation_patterns_examples` — tone, pace, emotional register (style reference, not copy source)

### Output
Base transcript (`RAW_PATTERN` version), **not** TTS-optimized:
- title, text, sectioned script, pattern plan, estimated duration, metadata
- status → `PENDING_ENHANCEMENT`

### Selection flow
1. Validate brief → 2. Select opening → 3. Settling → 4. Body → 5. Breath → 6. Mind/heart → 7. Closing → 8. Pull nearest examples → 9. Generate → 10. Estimate duration → 11. Save raw

### Example pattern chain
`guidedmeditationintro` → `groundingsettlingposture` → `softeningsettlingawareness` → `breathattention` → `mindreframingoneness` → `closingtransition`

## Agent 2 — ElevenLabs Script Doctor

### Inputs
`transcript_id`, `raw_version_id`, `voice_model` (e.g. `eleven_multilingual_v2`, `eleven_v3`), `output_mode`

### Output modes
| Mode | Use case |
|------|----------|
| `plain_paste` | Clean paragraphs/beats for manual ElevenLabs UI paste |
| `api_chunked` | Chunked output with `previous_text`/`next_text` continuity for API |
| `v3_tagged` | Chunked + sparse v3 audio tags for expressive narration |

### Output artifacts
Enhanced full script, beat-grouped script, chunked script, voice direction notes, pronunciation notes, optional v3 tags, per-chunk duration estimates

### Rewrite rules (apply in order)
1. **Structural cleanup** — remove fillers, duplicates, artifacts; complete sentence fragments
2. **Ear-first rewrite** — one idea per sentence; short/medium length; rhythm variation; short beats
3. **Punctuation control** — periods for rests, commas for micro-pauses; sparing dashes/colons; minimal ellipses
4. **Token normalization** — numbers, acronyms, units to spoken form; pronunciation notes for unstable terms
5. **Chunking** — manageable synthesis chunks with continuity context
6. **Optional v3 tagging** — light inline tags aligned with emotional register

## Data Model

Immutable versions under one transcript entity. **Never overwrite transcript text in place.**

### Tables
- `transcript` — entity, taxonomy fields, status, `current_version_id`, `enhancement_attempt_count`, `last_error`
- `transcript_version` — `version_kind`, `content_text`, `content_json`, `created_by_agent`, `metadata_json`
- `transcript_job_event` — audit trail

### Status values
`CREATED` → `PENDING_ENHANCEMENT` → `ENHANCING` → `ENHANCED` | `FAILED_ENHANCEMENT` | `REVIEW_REQUIRED`

### Version kinds
- `RAW_PATTERN` (Agent 1)
- `ELEVENLABS_ENHANCED` (Agent 2)
- `ELEVENLABS_TAGGED`, `APPROVED_FINAL` (future)

## SQS Message Contract

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

## Transaction Rules

### Lambda 1
Insert transcript (if needed) → insert `RAW_PATTERN` version → status `PENDING_ENHANCEMENT` → commit → publish SQS message

### Lambda 2
Load by ID → atomic `PENDING_ENHANCEMENT` → `ENHANCING` → generate → insert `ELEVENLABS_ENHANCED` → update `current_version_id` + status `ENHANCED` → commit

## Idempotency & Retry

- SQS/Lambda can deliver duplicates — Lambda 2 must be safe to re-run
- Use `idempotency_key` in queue message
- Uniqueness constraint on enhancement per raw version + strategy
- Track `enhancement_attempt_count`
- Transient failure → SQS retry; repeated → DLQ; quality issue → `REVIEW_REQUIRED`

## AWS Stack

| Layer | Service |
|-------|---------|
| API | API Gateway + FastAPI or Lambda |
| Agent 1 & 2 | AWS Lambda |
| Persistence | Aurora PostgreSQL (+ optional RDS Proxy) |
| Async handoff | SQS + DLQ |
| Secrets | AWS Secrets Manager |
| Observability | CloudWatch (logs, alarms, metrics) |

## Codebase Layout

```
api/                  # Intake API
transcript_composer/  # Agent 1
tts_enhancer/         # Agent 2
db/                   # Repositories, transactions, migrations
queues/               # SQS message contracts
models/               # Shared DTOs and persistence models
observability/        # Metrics and logging
infra/                # AWS infrastructure
```

See [`guide/phase-0-foundation.md`](phase-0-foundation.md) for technology and environment decisions.

## Out of Scope (This Phase)

Audio generation, voice cloning, ElevenLabs API execution, subtitle timecoding, video rendering, visual scene planning, publishing workflows, creative content beyond transcript + TTS enhancement.

## Key Metrics

Transcripts created, pending enhancement count, enhancement latency/failure rate, queue depth, oldest message age, Lambda duration/errors, Aurora write errors, DLQ depth.

## Security

Secrets Manager for credentials; least-privilege IAM per Lambda; protect PII/tenant context in logs; reserved concurrency on Agent 2; DLQ alarms.
