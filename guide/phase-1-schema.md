# Phase 1 — Data Model and Schema

> Status: **complete** — schema deployed on Aurora dev (`001` at head)  
> Migration: [`db/migrations/versions/001_initial_schema.py`](../db/migrations/versions/001_initial_schema.py)

## What was built

### Tables

| Table | Key columns |
|-------|-------------|
| `transcript` | `id`, `tenant_id`, `asset_id`, taxonomy fields, `status`, `current_version_id`, `enhancement_attempt_count`, `last_error`, timestamps |
| `transcript_version` | `id`, `transcript_id`, `version_kind`, `content_text`, `content_json`, `metadata_json`, `source_version_id`, `enhancement_mode`, `created_by_agent` |
| `transcript_job_event` | `id`, `transcript_id`, `event_type`, `event_payload`, `created_at` |

### Constraints

- **Status** `CHECK` — all six lifecycle values
- **Version kind** `CHECK` — `RAW_PATTERN`, `ELEVENLABS_ENHANCED`, `ELEVENLABS_TAGGED`, `APPROVED_FINAL`
- **Enhancement mode** `CHECK` — `plain_paste`, `api_chunked`, `v3_tagged` (nullable on raw versions)
- **Idempotency** — partial unique index on `(source_version_id, enhancement_mode)` for Lambda 2

### Python enums

[`models/enums.py`](../models/enums.py) — `TranscriptStatus`, `VersionKind`, `EnhancementMode`

## Apply locally

```bash
docker compose up -d
set CREATIVE_AGENT_DATABASE_URL=postgresql://creative_agent:creative_agent@localhost:5432/creative_agent
alembic -c db/alembic.ini upgrade head
python -m pytest tests/test_migrations.py -v
```

## Rollback

```bash
alembic -c db/alembic.ini downgrade -1    # one step
alembic -c db/alembic.ini downgrade base # full reset (dev only)
```

See [`db/README.md`](../db/README.md).

## Note: `queues/` rename

The SQS module is `queues/` (not `queue/`) to avoid shadowing Python's stdlib `queue` module.

**Next phase:** [Phase 2 — Domain contracts and shared models](transcript-enhancement-phase-map.md#phase-2--domain-contracts-and-shared-models)
