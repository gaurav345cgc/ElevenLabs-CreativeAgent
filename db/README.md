# Database migrations

Alembic migrations for Aurora PostgreSQL. Schema matches [`guide/DetailedBreakdown.md`](../guide/DetailedBreakdown.md) and Phase 1 of the [phase map](../guide/transcript-enhancement-phase-map.md).

## Tables

| Table | Purpose |
|-------|---------|
| `transcript` | Canonical transcript entity, taxonomy fields, status, current version pointer |
| `transcript_version` | Immutable script versions (`RAW_PATTERN`, `ELEVENLABS_ENHANCED`, …) |
| `transcript_job_event` | Audit trail for status transitions and operational events |

### Extra columns (idempotency)

`transcript_version` includes `source_version_id` and `enhancement_mode` so Lambda 2 cannot create duplicate enhanced versions for the same raw version and output mode (partial unique index).

## Commands

From repository root, with `CREATIVE_AGENT_DATABASE_URL` set:

```bash
# Apply all migrations
alembic -c db/alembic.ini upgrade head

# Roll back one revision
alembic -c db/alembic.ini downgrade -1

# Roll back entire schema
alembic -c db/alembic.ini downgrade base

# Show current revision
alembic -c db/alembic.ini current
```

## Local database

```bash
docker compose up -d
set CREATIVE_AGENT_DATABASE_URL=postgresql://creative_agent:creative_agent@localhost:5432/creative_agent
alembic -c db/alembic.ini upgrade head
```

On Unix:

```bash
export CREATIVE_AGENT_DATABASE_URL=postgresql://creative_agent:creative_agent@localhost:5432/creative_agent
```

## Rollback strategy

1. **Single step:** `alembic downgrade -1` runs the `downgrade()` in the latest migration (drops indexes, FKs, tables in safe order).
2. **Full reset:** `alembic downgrade base` removes all revisions; use only in dev/staging.
3. **Production:** never edit applied migrations; add a new forward migration for schema changes.
4. **Failed deploy:** if `upgrade` fails mid-transaction, Alembic rolls back the current migration transaction; fix the migration or DB state, then re-run `upgrade head`.

## Status and version constraints

Enforced via `CHECK` constraints aligned with [`models/enums.py`](../models/enums.py):

- **Status:** `CREATED`, `PENDING_ENHANCEMENT`, `ENHANCING`, `ENHANCED`, `FAILED_ENHANCEMENT`, `REVIEW_REQUIRED`
- **Version kind:** `RAW_PATTERN`, `ELEVENLABS_ENHANCED`, `ELEVENLABS_TAGGED`, `APPROVED_FINAL`
- **Enhancement mode:** `plain_paste`, `api_chunked`, `v3_tagged` (nullable on raw versions)
