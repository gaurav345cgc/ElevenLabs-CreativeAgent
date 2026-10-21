# TTS Phase 0 — Boundary Definition

> Status: **complete**  
> Spec: [`tts-plane-phase-map.md`](tts-plane-phase-map.md) · [`architecture-and-tts-plane.md`](architecture-and-tts-plane.md)

## Confirmed boundary (checklist)

| Item | Decision |
|------|----------|
| Entry condition | TTS plane starts only when transcript status is **`ENHANCED`** and an **`ELEVENLABS_ENHANCED`** version exists |
| Script meaning | TTS plane **does not** rewrite transcript meaning — synthesis only |
| Binary storage | Audio artifacts in **S3**; Aurora stores **metadata** only |
| Code location | Separate segment folder **`tts_pipeline/`** at repo root |
| Repo model | **Same monorepo** as transcript pipeline — shared DB, AWS account, deploy tooling |
| Voice config | **Voice policy layer** — approved profiles; not raw caller-controlled ElevenLabs params |
| Idempotency | **Chunk-level** idempotency; safe under Step Functions / Lambda retries |
| Partial work | **Partial regeneration** supported — single-chunk replay without redoing completed chunks |
| Provider metadata | Persist request IDs, response headers, byte size, checksum for debug and cost tracking |

## Plane separation

| Plane | Responsibility | Must not |
|-------|----------------|----------|
| Transcript (`transcript_composer/`, `tts_enhancer/`) | Compose + enhance text; store versioned transcripts | Generate audio, call ElevenLabs TTS |
| TTS (`tts_pipeline/`) | Chunk plan → ElevenLabs Create speech → S3 → manifest | Compose or enhance script text |
| API (`api/`) | Transcript status/versions today; audio job APIs later | Couple Agent 1 and Agent 2 handlers |

## `tts_pipeline/` module map

```
tts_pipeline/
├── intake/           # Create TTS jobs from enhanced transcripts
├── orchestrator/     # Step Functions / workflow lifecycle
├── chunk_planner/    # Split enhanced transcript into generation chunks
├── generator/        # ElevenLabs client + audio output writes
├── finalizer/        # Manifest assembly + job completion
├── voice_policy/     # Approved voice/model/format profiles
└── persistence/      # Aurora audio job/chunk/asset writes
```

Upstream reads **`ELEVENLABS_ENHANCED`** from `transcript_version` via existing `db/` repositories — TTS plane does not duplicate transcript tables.

## Out of scope (TTS plane)

- Transcript composition or enhancement
- Video rendering, subtitles, music mixing, mastering
- Speech-to-text
- User-facing script editing

## Exit criteria

- [x] Boundary and responsibilities approved (this document + master spec §4–7).
- [x] No overlap with transcript enhancement logic — all new code under `tts_pipeline/`.

**Next phase:** [TTS Phase 1 — repo and folder additions](tts-plane-phase-map.md#2-phase-1--repo-and-folder-additions) → then [TTS Phase 2 — data model](tts-plane-phase-map.md#3-phase-2--data-model).
