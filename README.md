# Creative Agent

In-house production subsystem: **Pattern Transcript Composer** → **ElevenLabs Script Doctor** → **TTS Orchestration Plane** (in progress).

Produces enhanced narration for ElevenLabs; the TTS plane will generate stored audio artifacts and manifests.

## Documentation

| Doc | Purpose |
|-----|---------|
| [`guide/architecture-and-tts-plane.md`](guide/architecture-and-tts-plane.md) | Master architecture — transcript plane + TTS plane |
| [`guide/AGENTS.md`](guide/AGENTS.md) | Transcript agents, invariants, data model |
| [`guide/DetailedBreakdown.md`](guide/DetailedBreakdown.md) | Full transcript specification |
| [`guide/transcript-enhancement-phase-map.md`](guide/transcript-enhancement-phase-map.md) | Transcript build checklist (complete) |
| [`guide/tts-plane-phase-map.md`](guide/tts-plane-phase-map.md) | **TTS plane build checklist** (active) |
| [`guide/phase-tts-0-boundary.md`](guide/phase-tts-0-boundary.md) | TTS Phase 0 — boundary decisions |
| [`guide/phase-0-foundation.md`](guide/phase-0-foundation.md) | Transcript Phase 0 decisions |

## Layout

```
api/                  Intake API (transcript status and versions)
transcript_composer/  Agent 1 — base transcript from pattern system
tts_enhancer/         Agent 2 — ElevenLabs-ready enhancement
tts_pipeline/         TTS plane — enhanced transcript → ElevenLabs audio → S3
db/                   Persistence and migrations
queues/               SQS contracts
models/               Shared DTOs and enums
observability/        Logging and metrics
infra/                AWS infrastructure
tests/                Unit and integration tests (tests/tts/ for TTS plane)
```

## Local setup

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e ".[dev]"
cp .env.example .env
docker compose up -d
alembic -c db/alembic.ini upgrade head
```

See [`db/README.md`](db/README.md) for rollback and migration details.

## Build order

**Transcript plane:** complete — [`guide/transcript-enhancement-phase-map.md`](guide/transcript-enhancement-phase-map.md).

**TTS plane (active):** [`guide/tts-plane-phase-map.md`](guide/tts-plane-phase-map.md). Phases 0–4 complete; next is **TTS Phase 5 — voice policy**.
