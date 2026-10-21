# Phase 4 — Persistence Layer

> Status: **complete**  
> Package: [`db/repositories/`](../db/repositories/)

## Components

| Component | Path |
|-----------|------|
| `TranscriptRepository` | `db/repositories/transcript_repository.py` |
| ORM mappings | `db/orm.py` |
| Status transition rules | `db/state.py` |
| Transaction scope + retry | `db/session.py` |
| Structured DB logging | `observability/logging.py` |

## Repository methods

- `create_transcript()`
- `insert_transcript_version()` — raises `DuplicateVersionError` on idempotency conflict
- `update_transcript_status()`
- `set_current_version()`
- `record_job_event()`
- `load_transcript_with_versions()`
- `claim_for_enhancement()` — atomic `PENDING_ENHANCEMENT` → `ENHANCING`
- `mark_enhancement_failed()`
- `find_enhanced_version()` — idempotency check helper for Agent 2

## Usage

```python
from db import TranscriptRepository, build_session_factory, session_scope
from db.repositories import CreateTranscriptInput

repo = TranscriptRepository(build_session_factory())
with session_scope(repo._session_factory) as session:
    transcript = repo.create_transcript(session, CreateTranscriptInput(...))
```

## Tests

```powershell
python -m pytest tests/test_state_transitions.py tests/test_transcript_repository.py -v
```

Integration tests require `CREATIVE_AGENT_DATABASE_URL` (Aurora or local Postgres).

**Next phase:** [Phase 5 — Pattern knowledge ingestion](transcript-enhancement-phase-map.md#phase-5--pattern-knowledge-ingestion)
