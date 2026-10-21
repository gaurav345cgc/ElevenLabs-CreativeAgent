# Phase 2 — Domain Contracts

> Status: **complete**  
> Package: [`models/`](../models/)

## Models

| Contract | Module | Purpose |
|----------|--------|---------|
| `CreateTranscriptRequest` | `models/requests.py` | Intake API / Agent 1 brief |
| `TranscriptRecord` | `models/records.py` | `transcript` table row |
| `TranscriptVersionRecord` | `models/records.py` | `transcript_version` table row |
| `EnhancementJobMessage` | `models/messages.py` | SQS handoff (re-exported from `queues/`) |
| `Agent1Output` | `models/agents.py` | Composer result before persist |
| `Agent2Output` | `models/agents.py` | Script Doctor result before persist |
| `ErrorEnvelope` | `models/errors.py` | API / worker errors |

## Metadata (`content_json` / `metadata_json`)

- `TaxonomyContext`, `SelectedPatternPlan`, `DurationEstimate`
- `RawPatternMetadata` — Agent 1 version metadata
- `EnhancedVersionMetadata` — Agent 2 version metadata
- `SectionedScriptContent`, `EnhancedScriptContent`, `NarrationChunk`

## Conventions

- **IDs:** `uuid.UUID` everywhere
- **Timestamps:** timezone-aware `datetime` (UTC)
- **Schema version:** `SCHEMA_VERSION = "1.0"` on messages and metadata
- **Idempotency key:** `{transcript_id}:{raw_version_id}:enhancement-v1`

## Validation

`models/validation.py` — seed rules for `guided_meditation` wound/stage/generation until Phase 5 loads the full pattern index.

**Next phase:** [Phase 3 — Infrastructure baseline](transcript-enhancement-phase-map.md#phase-3--infrastructure-baseline)
