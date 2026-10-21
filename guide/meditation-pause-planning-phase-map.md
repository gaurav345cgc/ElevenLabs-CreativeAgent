# Meditation Pause Planning — Phase Map and Build Checklist

This is the **ultra-detailed implementation checklist** for intentional meditation silence holds: OpenAI decides where the voice stops and for how many seconds; the TTS stitch inserts silence; background bed continues through the holds.

**Master spec:** [`meditation-pause-planning.md`](meditation-pause-planning.md)  
**TTS architecture:** [`architecture-and-tts-plane.md`](architecture-and-tts-plane.md)  
**Upstream TTS phases:** [`tts-plane-phase-map.md`](tts-plane-phase-map.md)  
**Background mix:** [`background-audio-mixing.md`](background-audio-mixing.md) (bed already fills narration silence)

**Authority rule:** Where this phase map and [`meditation-pause-planning.md`](meditation-pause-planning.md) disagree, **the master spec wins**.

This document assumes the following is already complete and stable:

- Agent 2 writes `ELEVENLABS_ENHANCED` with `beats[]` / `content_text`.
- TTS workflow: `LoadEnhancedTranscript` → `PlanChunks` → generate → `FinalizeFinal` → `MixBackground` → manifest.
- `merge_mp3_chunks()` concatenates speech chunk bytes via ffmpeg.
- Background mix ducks bed under narration; silence in `final.mp3` already lets the bed rise.
- OpenAI credentials already exist for Agent 1/2 (`CREATIVE_AGENT_OPENAI_API_KEY` / model-provider secret).

---

## 0) What this feature does

1. Load enhanced transcript beats (or paragraphs).
2. Call OpenAI with a strict pause-planning prompt + schema.
3. Normalize / clamp a **PausePlan**.
4. Persist plan on the audio job (idempotent).
5. Map holds onto `after_chunk_index` after chunk planning.
6. Generate speech with ElevenLabs unchanged (no silence text).
7. At `FinalizeFinal`, interleave silence MP3s between speech chunks.
8. Mix background as today → `master.mp3` with holds filled by bed.

### Locked product decisions (copy from master spec)

| Decision | Choice |
|----------|--------|
| Planner | OpenAI structured JSON |
| When | After load transcript; before generation |
| Realize silence | Stitch / `FinalizeFinal` |
| Bed | Existing mix — no special hold mode |
| API caller control | None in v1 |
| Transcript plane | Do not change Agent 1/2 |

### Target workflow (after all phases complete)

```text
ValidateInput
  → CreateAudioJob
  → LoadEnhancedTranscript
  → PlanPauses                 ← NEW
  → PlanChunks
  → MapPausesToChunks          ← NEW (may be function called at end of PlanPauses or PlanChunks)
  → PersistChunkPlan           ← persist mapped plan too
  → GenerateChunksSequentially
  → RegisterAssets
  → FinalizeFinal              ← speech + silence intercalation
  → MixBackground
  → FinalizeManifest
  → MarkCompleted
  → Succeeded
```

### Artifact flow

```text
beats / paragraphs
       ↓
  PausePlan (after_beat_index, hold_seconds)
       ↓
  PlannedChunks (speech)
       ↓
  MappedPausePlan (after_chunk_index, hold_seconds)
       ↓
  ElevenLabs chunk MP3s
       ↓
  final.mp3 = speech ⟂ silence ⟂ speech ...
       ↓
  master.mp3 = final + bed (ducking)
```

### Phase overview

| Phase | Title | Slice |
|-------|-------|-------|
| **0** | Boundary definition | — |
| **1** | Pause schema models | 1 |
| **2** | Pause policy constants + clamps | 1 |
| **3** | OpenAI planner client | 1 |
| **4** | Prompt + structured output contract | 1 |
| **5** | Planner unit tests (mocked OpenAI) | 1 |
| **6** | Beat/paragraph extraction helpers | 1 |
| **7** | Map holds → chunk indices | 2 |
| **8** | Persist plan on job + events | 2 |
| **9** | Silence MP3 generator (ffmpeg) | 2 |
| **10** | Stitch intercalation | 2 |
| **11** | Finalizer service wiring | 2 |
| **12** | Workflow states `PlanPauses` (+ map) | 3 |
| **13** | Engine transitions + policies | 3 |
| **14** | Orchestrator / mapping tests | 3 |
| **15** | Observability | 4 |
| **16** | Manifest + API surface | 4 |
| **17** | Operator smoke scripts | 5 |
| **18** | E2E validation + listening QA | 5 |
| **19** | Rollout + docs closeout | 5 |

### Slice merge strategy

| Slice | Phases | Touches live workflow? | Needs OpenAI in prod? |
|-------|--------|------------------------|------------------------|
| **Slice 1** | 0–6 | No | No (mocked) |
| **Slice 2** | 7–11 | No (callable in isolation) | No |
| **Slice 3** | 12–14 | Yes — jobs get holds | Yes |
| **Slice 4** | 15–16 | Yes — operators see plan | Yes |
| **Slice 5** | 17–19 | Yes — E2E proven | Yes |

Phases must be completed in order within each slice. Slices can merge independently if later slices are not yet wired.

```text
Phase 0 (boundary)
    ↓
Phase 1 → 2 → 3 → 4 → 5 → 6          Slice 1 — planner pure
    ↓
Phase 7 → 8 → 9 → 10 → 11            Slice 2 — map + silence stitch
    ↓
Phase 12 → 13 → 14                   Slice 3 — workflow
    ↓
Phase 15 → 16                        Slice 4 — ops surface
    ↓
Phase 17 → 18 → 19                   Slice 5 — E2E + closeout
```

---

## 1) Phase 0 — boundary definition

### Goal

Lock scope so pause planning does not leak into Agent 1/2 or invent spoken pause directions.

### Prerequisites

- TTS plane finalization + background mix path understood.
- Master spec approved: [`meditation-pause-planning.md`](meditation-pause-planning.md).

### Checklist — in scope

- [x] OpenAI pause planner produces structured holds only
- [x] Holds attach to beat/paragraph indices, then map to chunk indices
- [x] Silence inserted at stitch (`FinalizeFinal`) — confirmed: `states.py::finalize_final` is the insertion point
- [x] Background mix unchanged — `mix.py` / `mix_background` state untouched
- [x] Plan persisted on audio job metadata — `transcript_audio_job.metadata_json` JSONB confirmed in `db/orm.py`
- [x] Duration budget: speech + holds ≈ target

### Checklist — out of scope

- [x] No Agent 1 / Agent 2 redesign
- [x] No "(pause N seconds)" in narrated text
- [x] No caller-driven pause seconds on `POST /audio-jobs` in v1
- [x] No SSML-as-primary mechanism
- [x] No new Aurora table required for v1

### Checklist — invariants (never violate)

- [x] Agent 2 still reads from DB only (unchanged)
- [x] Never overwrite raw / enhanced transcript content for pause reasons
- [x] TTS plane does not rewrite script meaning
- [x] Chunk generation remains idempotent
- [x] Pause plan reuse on SQS / workflow retry (no random re-plan)
- [x] Voice policy / background policy remain server-side

### Exit criteria

- [x] This phase map + master spec are the build authority
- [x] **Fail job on planner failure** (v1) — locked; no silent empty-plan fallback

### Locked decisions (Phase 0 closeout)

| Decision | Locked value |
|----------|--------------|
| Planner failure behavior | **Fail job** — no silent fallback in v1 |
| Preferred anchors | **beats[]** first; paragraphs from `content_text` as fallback |
| Silence insertion point | `FinalizeFinal` stitch only |
| Plan storage | `transcript_audio_job.metadata_json` — no new table |
| Background mix | **Unchanged** |
| Package location | `tts_pipeline/pause_planner/` — mirrors `voice_policy/` / `background_policy/` |

**Phase 0 complete.**

---

## 2) Phase 1 — pause schema models

### Goal

Define typed models for planner I/O and mapped plans.

### Prerequisites

- Phase 0 complete.

### Files to create / modify

| File | Change |
|------|--------|
| `tts_pipeline/pause_planner/schema.py` | Pydantic models |
| `tts_pipeline/pause_planner/__init__.py` | Exports |
| `tests/tts/test_pause_planner_schema.py` | Round-trip + validation stub |

**Preferred package:** `tts_pipeline/pause_planner/` (mirrors `voice_policy/`, `background_policy/`) — keep transcript `models/` free of TTS-only planner details unless shared API needs them.

### Checklist — enums

- [x] `PauseHoldKind`: `practice` | `section` | `integration` | `other`
- [x] `PausePlannerProvider`: `openai` (extensible)

### Checklist — models

- [x] `PauseHold`:
  - [x] `hold_id: str`
  - [x] `after_beat_index: int | None`
  - [x] `after_paragraph_index: int | None`
  - [x] `hold_seconds: int` (ge 1)
  - [x] `kind: PauseHoldKind`
  - [x] `reason: str` (non-empty, max length e.g. 240)
- [x] `PausePlan`:
  - [x] `schema_version: str = "1.0"`
  - [x] `planner: PausePlannerProvider`
  - [x] `model: str`
  - [x] `prompt_version: str`
  - [x] `policy_version: str`
  - [x] `target_duration_seconds: int | None`
  - [x] `estimated_speech_seconds: int | None`
  - [x] `total_hold_seconds: int`
  - [x] `holds: list[PauseHold]`
  - [x] `raw_response_sha256: str | None` (optional audit)
- [x] `MappedPauseHold`:
  - [x] all of `PauseHold` fields kept for audit
  - [x] `after_chunk_index: int` (ge 0)
- [x] `MappedPausePlan`:
  - [x] `schema_version`, `holds: list[MappedPauseHold]`, `total_hold_seconds`

### Checklist — validation rules on models

- [x] Exactly one of `after_beat_index` / `after_paragraph_index` required at planner output stage (or beat preferred when beats exist)
- [x] `hold_id` unique within plan
- [x] `total_hold_seconds == sum(hold_seconds)` after normalize (schema recomputes on validate; policy normalizer in Phase 2 also recomputes)

### Exit criteria

- [x] Models import cleanly; no workflow imports yet
- [x] Round-trip JSON dump/load works in `tests/tts/test_pause_planner_schema.py` (full planner tests in Phase 5)

**Phase 1 complete.**

## 3) Phase 2 — pause policy constants and clamps

### Goal

Server-side policy for hold bounds and duration budgeting — not caller-driven.

### Prerequisites

- Phase 1 complete.

### Files created

| File | Change |
|------|--------|
| `tts_pipeline/pause_planner/policy.py` | Constants + clamp/budget helpers |
| `tts_pipeline/pause_planner/errors.py` | `PausePlannerError` |
| `tests/tts/test_pause_planner_policy.py` | Policy unit tests |

Optional `profiles.py` skipped for v1 — single default policy is enough.

### Checklist — constants

- [x] `PAUSE_POLICY_VERSION = "pause-v1"`
- [x] `PROMPT_VERSION = "pause-prompt-v1"`
- [x] `MIN_HOLD_SECONDS = 5`
- [x] `MAX_HOLD_SECONDS = 90`
- [x] Defaults by kind:
  - [x] practice: prefer 8–15 (clamp 5–20)
  - [x] section: prefer 20–40 (clamp 15–45)
  - [x] integration: prefer 30–60 (clamp 30–90)
- [x] `MAX_HOLDS_PER_JOB` (24)
- [x] `DURATION_TOLERANCE_RATIO = 0.15`
- [x] `DEFAULT_FAIL_ON_PLANNER_ERROR = True`

### Checklist — functions

- [x] `clamp_hold_seconds(seconds: int, kind: PauseHoldKind) -> int`
- [x] `normalize_pause_plan(plan: PausePlan, *, target_duration_seconds, estimated_speech_seconds) -> PausePlan`
  - [x] clamp each hold
  - [x] v1: clamp into range (do not drop solely for being below min before clamp)
  - [x] recompute `total_hold_seconds`
  - [x] over budget → scale holds down proportionally (integer seconds, min clamp)
  - [x] if still over → drop lowest-priority holds (`other` then shortest `practice`, then section/integration); log
- [x] `validate_pause_plan_anchors(plan, *, beat_count, paragraph_count) -> None` raises `PausePlannerError`

### Exit criteria

- [x] Pure functions; no I/O
- [x] Documented behavior for over-budget scaling (module docstring in `policy.py`)

**Phase 2 complete.**

## 4) Phase 3 — OpenAI planner client

### Goal

Thin client that calls OpenAI and returns parsed JSON (pre-normalize).

### Prerequisites

- Phase 1–2 complete.
- Reuse existing OpenAI key loading patterns from `transcript_composer` / enhancer (do not invent a third secrets path).

### Files created

| File | Change |
|------|--------|
| `tts_pipeline/pause_planner/openai_client.py` | HTTP/SDK call wrapper |
| `tts_pipeline/pause_planner/errors.py` | `PausePlannerError`, `PausePlannerTransientError`, `PausePlannerValidationError` |
| `tests/tts/test_pause_planner_openai_client.py` | Fake transport + retry tests |

### Checklist

- [x] Resolve API key from env / Secrets Manager via `transcript_composer.llm_config.require_openai_api_key`
- [x] Configurable model via env `CREATIVE_AGENT_PAUSE_PLANNER_MODEL` (fallback `CREATIVE_AGENT_OPENAI_MODEL`, default `gpt-4o-mini`)
- [x] Timeout + retry (default 3 attempts) on transient errors only
- [x] `plan_pauses(*, beats, paragraphs, target_duration_seconds, estimated_speech_seconds, ...) -> dict` raw
- [x] Use JSON mode (`response_format=json_object`)
- [x] Temperature ≤ 0.3 (default 0.2; constructor rejects higher)
- [x] Never log full API key; redact Authorization-like exception text
- [x] Record latency on `client.last_latency_ms` (metrics wiring in Phase 15)

### Exit criteria

- [x] Client can be constructed in unit tests with a fake transport / monkeypatch (`create_completion=`)
- [x] No import of orchestrator or finalizer

**Phase 3 complete.** Minimal fallback prompts live in `openai_client.py` until Phase 4 extracts `prompt.py`.

## 5) Phase 4 — prompt and structured output contract

### Goal

Stable prompt that forbids rewriting and forces hold anchors.

### Prerequisites

- Phase 3 complete.

### Files created

| File | Change |
|------|--------|
| `tts_pipeline/pause_planner/prompt.py` | System + user prompt builders + `parse_pause_plan_response` |
| `tests/tts/test_pause_planner_prompt.py` | Prompt + parser tests |
| `tts_pipeline/pause_planner/openai_client.py` | Uses `build_system_prompt` / `build_user_prompt` |

### Checklist — system prompt must include

- [x] Role: meditation pause planner for guided audio
- [x] Output JSON only matching schema
- [x] **Do not rewrite, shorten, or add spoken words**
- [x] Prefer holds after instructions and section changes
- [x] Avoid holds after pure connective lines
- [x] Prefer fewer longer holds over many short ones
- [x] Respect min/max seconds and approximate duration budget
- [x] `reason` must be short and operational (why the listener needs silence)
- [x] Use `after_beat_index` when beats are provided; else `after_paragraph_index`

### Checklist — user prompt must include

- [x] Numbered beats: `0: ...`, `1: ...`
- [x] `target_duration_seconds`, `estimated_speech_seconds`, remaining budget hint
- [x] Policy bounds table
- [x] Example of good vs bad hold placement (short)

### Checklist — response schema (JSON)

- [x] Parser maps into `PauseHold` / `PausePlan` (`parse_pause_plan_response`)
- [x] Assign `planner`, `model`, `prompt_version`, `policy_version` server-side (do not trust model)

### Exit criteria

- [x] Prompt versions are constants referenced by `PROMPT_VERSION`
- [x] Changing prompt requires bumping `PROMPT_VERSION` (documented in `prompt.py` module docstring)

**Phase 4 complete.**

## 6) Phase 5 — planner unit tests (mocked OpenAI)

### Goal

Lock schema, clamps, and prompt parsing without live API cost.

### Prerequisites

- Phase 1–4 complete.

### Files

| File | Role |
|------|------|
| `tests/tts/test_pause_planner_schema.py` | Model validation |
| `tests/tts/test_pause_planner_policy.py` | Clamps + budget scaling + anchor validation |
| `tests/tts/test_pause_planner_openai_client.py` | Transport, retries, malformed JSON |
| `tests/tts/test_pause_planner_prompt.py` | Prompt + parser |
| `tests/tts/test_pause_planner_client.py` | Mock OpenAI → parse → normalize |

### Checklist

- [x] Valid plan parses
- [x] Out-of-range seconds clamp
- [x] Over-budget proportional scale
- [x] Duplicate `hold_id` rejected
- [x] Invalid beat index rejected by validator
- [x] Mock OpenAI returns holds → normalize succeeds
- [x] Malformed JSON → `PausePlannerValidationError`
- [x] Empty holds list allowed (v1): documented in `policy.py`; tested in `test_pause_planner_client.py`

### Exit criteria

- [x] `pytest tests/tts/test_pause_planner_*.py` passes (run five files on Windows: schema, policy, openai_client, prompt, client)
- [x] **Slice 1 planner core ready**

**Phase 5 complete.**

## 7) Phase 6 — beat / paragraph extraction helpers

### Goal

Deterministic anchors from `TranscriptVersionRecord` for the planner input.

### Prerequisites

- Phase 1 complete (can parallelize with 2–5).

### Files created

| File | Change |
|------|--------|
| `tts_pipeline/pause_planner/anchors.py` | `PauseAnchors` + `extract_pause_anchors` |
| `tests/tts/test_pause_planner_anchors.py` | Unit tests with sample enhanced content_json |

Reuses `tts_pipeline/chunk_planner/sentences.py::split_paragraphs`.

### Checklist

- [x] `extract_pause_anchors(version) -> PauseAnchors(beats, paragraphs, preferred: "beats"|"paragraphs")`
- [x] Prefer `content_json.beats` when non-empty list of non-blank strings
- [x] Else split `content_text` into paragraphs
- [x] Strip whitespace; reject empty anchors
- [x] If both empty → raise `PausePlannerValidationError`

### Exit criteria

- [x] Unit tests with sample enhanced content_json
- [x] **Slice 1 complete**

**Phase 6 complete. Slice 1 (Phases 0–6) complete.**

## 8) Phase 7 — map holds → chunk indices

### Goal

Translate `after_beat_index` / `after_paragraph_index` into `after_chunk_index` after `plan_chunks_from_version`.

### Prerequisites

- Phase 6 complete; chunk planner stable.

### Files created

| File | Change |
|------|--------|
| `tts_pipeline/pause_planner/mapping.py` | Mapping algorithm |
| `tests/tts/test_pause_planner_mapping.py` | 1:1, merged, split, deterministic, errors |

### Mapping algorithm (v1) — implemented

1. Speech units = beats if preferred else paragraphs
2. Greedy whitespace-normalized containment; proportional fallback with warning
3. Hold unit index → chunk index
4. Same-chunk holds: sum seconds, highest severity kind, join reasons
5. Holds after last chunk allowed (trailing silence before bed tail)
6. Sort by `after_chunk_index`

### Checklist

- [x] `map_pause_plan_to_chunks(plan, chunks, anchors) -> MappedPausePlan`
- [x] Deterministic for same inputs
- [x] Unit tests: 1:1 beat-per-chunk; merged beats into one chunk; split paragraph into many chunks

### Exit criteria

- [x] Mapping has no OpenAI dependency
- [x] Failures raise `PausePlannerValidationError` with clear message

**Phase 7 complete.**

## 9) Phase 8 — persist plan on job + events

### Goal

Store plans for idempotency, audit, and replay without re-calling OpenAI.

### Prerequisites

- Phase 1, 7 complete.

### Files created / modified

| File | Change |
|------|--------|
| `tts_pipeline/pause_planner/service.py` | `create_or_load_pause_plan`, `persist_mapped_pause_plan`, stores |
| `db/repositories/audio_job_repository.py` | `merge_audio_job_metadata()` |
| `tests/tts/test_pause_planner_service.py` | In-memory store + idempotency tests |

Orchestrator context wiring deferred to Phase 12.

### Checklist — metadata keys

- [x] `metadata_json["pause_plan"]` = PausePlan dict
- [x] `metadata_json["mapped_pause_plan"]` = MappedPausePlan dict
- [x] `metadata_json["pause_plan_versions"]` = `{policy_version, prompt_version, model}`

### Checklist — idempotent service behavior

- [x] If `pause_plan` already present and versions match → return existing (no OpenAI / factory call)
- [x] If versions mismatch and `force_replan=False` → keep existing (log); only replan when `force_replan=True`
- [x] Record events:
  - [x] `PAUSE_PLAN_CREATED`
  - [x] `PAUSE_PLAN_REUSED`
  - [x] `PAUSE_PLAN_MAPPED`
  - [x] `PAUSE_PLAN_CLAMPED` (before/after totals)

### Exit criteria

- [x] Service unit test with fake repo / in-memory metadata dict (`InMemoryPausePlanStore`)
- [x] SQS duplicate safe: second run does not change plan

**Phase 8 complete.**

## 10) Phase 9 — silence MP3 generator (ffmpeg)

### Goal

Generate silent MP3 bytes of N seconds for intercalation.

### Prerequisites

- ffmpeg available (`resolve_ffmpeg_executable`).

### Files created

| File | Change |
|------|--------|
| `tts_pipeline/finalizer/silence.py` | `generate_silence_mp3` + `SilenceGenerationError` |
| `tests/tts/test_silence.py` | Validation, cache, 3s ffprobe smoke |

### Checklist

- [x] Use ffmpeg `anullsrc` → `libmp3lame`
- [x] Match bitrate defaults used by stitch (`128k`)
- [x] Validate `duration_seconds >= 1`
- [x] Cap generation at `MAX_HOLD_SECONDS`
- [x] Raise `SilenceGenerationError` (subclass of `FinalMergeError`) on failure
- [x] Optional: cache by duration inside a single stitch invocation (dict)

### Exit criteria

- [x] Unit/smoke: generate 3s silence, file non-empty, ffprobe duration ≈ 3s (±0.15s)

**Phase 9 complete.**

## 11) Phase 10 — stitch intercalation

### Goal

Extend merge path to accept optional silence after specific chunk indices.

### Prerequisites

- Phase 9 complete.

### Files modified

| File | Change |
|------|--------|
| `tts_pipeline/finalizer/stitch.py` | `merge_mp3_chunks_with_holds` |
| `tests/tts/test_final_merge.py` | Intercalation + empty-holds + validation |

### Checklist — API shape

- [x] Additive API: `merge_mp3_chunks_with_holds(chunk_bytes, holds)` where holds are `(after_chunk_index, hold_seconds)`
- [x] Keep `merge_mp3_chunks(...)` unchanged
- [x] Build ordered media list: chunk then silences for that index
- [x] Reject `after_chunk_index` out of range
- [x] Empty holds → identical behavior to today’s merge

### Exit criteria

- [x] Test: 2 speech chunks + 5s hold after index 0 → duration ≈ sum(speech)+5
- [x] Test: no holds → byte-identical to plain merge

**Phase 10 complete.**

## 12) Phase 11 — finalizer service wiring

### Goal

`finalize_audio_job_final` reads mapped pause plan and uses intercalating merge.

### Prerequisites

- Phase 8, 10 complete.

### Files modified

| File | Change |
|------|--------|
| `tts_pipeline/finalizer/service.py` | Load mapped plan; call `merge_mp3_chunks_with_holds` |
| `tests/tts/test_manifest_finalizer.py` | Integration test with injected mapped holds |

Manifest pause summary fields deferred to Phase 16.

### Checklist

- [x] Read `job.metadata_json["mapped_pause_plan"]` if present
- [x] Convert to `(after_chunk_index, hold_seconds)` list
- [x] Pass into merge-with-holds
- [x] If missing mapped plan → legacy merge (speech only)
- [x] Store in finalization metadata / events: `total_hold_seconds`, `hold_count`
- [x] Extend existing `FINAL_MERGED` payload (no separate event name required)

### Exit criteria

- [x] **Slice 2 complete** — can finalize a job with injected metadata holds without workflow state yet
- [x] Integration-style test with fake chunks + metadata

**Phase 11 complete. Slice 2 (Phases 7–11) complete.**

## 13) Phase 12 — workflow states `PlanPauses` (+ map)

### Goal

Add explicit replayable states for pause planning and mapping.

### Prerequisites

- Phase 8, 11 complete.

### Files modified

| File | Change |
|------|--------|
| `tts_pipeline/orchestrator/workflow.py` | Add `PLAN_PAUSES`, `MAP_PAUSES_TO_CHUNKS` |
| `tts_pipeline/orchestrator/states.py` | `plan_pauses` / `map_pauses_to_chunks` handlers |
| `tts_pipeline/pause_planner/openai_client.py` | Public `model` property for plan factory |
| `tests/tts/test_pause_planner_states.py` | Handler unit tests with fakes |

Engine transitions deferred to Phase 13 (Option A locked).

### Decision (locked)

**Option A:** two states — `PlanPauses` (OpenAI + persist `pause_plan`) then `MapPausesToChunks` (after `PlanChunks`, persist `mapped_pause_plan`).

### Target order (for Phase 13 wiring)

```text
LoadEnhancedTranscript
  → PlanPauses              ← OpenAI + persist pause_plan
  → PlanChunks
  → MapPausesToChunks       ← map + persist mapped_pause_plan
  → PersistChunkPlan
  → GenerateChunksSequentially
  ...
```

### Checklist — `plan_pauses` handler

- [x] Reload job + transcript version
- [x] `extract_pause_anchors`
- [x] `create_or_load_pause_plan` (OpenAI if missing; injectable `plan_factory`)
- [x] Store on job metadata inside transaction (`SessionPausePlanStore`)
- [x] Put plan summary on `ctx.metadata`

### Checklist — `map_pauses_to_chunks` handler

- [x] Require `pause_plan` present
- [x] Require planned chunks present (from ctx or DB)
- [x] Map + persist `mapped_pause_plan`
- [x] Put mapped summary on `ctx.metadata`

### Exit criteria

- [x] Handlers exist and are unit-testable with fakes
- [x] Replay: start at `MapPausesToChunks` with existing `pause_plan` does not call OpenAI

**Phase 12 complete.**

## 14) Phase 13 — engine transitions and state policies

### Goal

Wire states into `TtsWorkflowEngine`.

### Prerequisites

- Phase 12 complete.

### Files modified

| File | Change |
|------|--------|
| `tts_pipeline/orchestrator/engine.py` | Transitions + transient retries |
| `tts_pipeline/orchestrator/config.py` | `STATE_POLICIES` for pause states |
| `infra/step_functions/tts_audio_job.asl.json` | Mirror PlanPauses / MapPausesToChunks |
| `tests/tts/test_orchestrator.py` | Ordering, transitions, PlanPauses failure |

### Checklist — transitions

- [x] `LOAD_ENHANCED_TRANSCRIPT` → `PLAN_PAUSES`
- [x] `PLAN_PAUSES` → `PLAN_CHUNKS`
- [x] `PLAN_CHUNKS` → `MAP_PAUSES_TO_CHUNKS`
- [x] `MAP_PAUSES_TO_CHUNKS` → `PERSIST_CHUNK_PLAN`
- [x] Remaining chain unchanged through `FINALIZE_FINAL` → mix → manifest

### Checklist — policies

- [x] `PlanPauses`: `max_attempts=3`, `timeout_seconds=60` (LLM)
- [x] `MapPausesToChunks`: `max_attempts=2`, `timeout_seconds=30`
- [x] Planner transient errors retryable; validation errors fail job

### Checklist — linear state validation list

- [x] Update ordering assertions in `tests/tts/test_orchestrator.py`

### Exit criteria

- [x] Engine executes full sequence including new states
- [x] Failure in `PlanPauses` never generates ElevenLabs audio

**Phase 13 complete.**

## 15) Phase 14 — orchestrator / mapping tests

### Goal

Lock ordering, idempotency, and stitch-with-holds behavior in automated tests.

### Prerequisites

- Phase 13 complete.

### Files to modify

| File | Change |
|------|--------|
| `tests/tts/test_orchestrator.py` | New state order |
| `tests/tts/test_pause_mapping.py` | Mapping edge cases |
| `tests/tts/test_final_merge_holds.py` | Stitch holds |

### Checklist

- [ ] Assert order includes `PlanPauses` → `PlanChunks` → `MapPausesToChunks`
- [ ] Mock OpenAI — called once; second workflow run reuses plan
- [ ] Mock merge-with-holds — verify silence durations passed
- [ ] Planner failure → job failed; no chunk generation
- [ ] Pre-feature job without pause metadata → legacy merge still works if starting mid-pipeline? (document: old jobs won’t have states; new deploys always plan)

### Exit criteria

- [ ] **Slice 3 complete** — workflow produces `final.mp3` with holds when planner returns holds
- [ ] pytest suites green

---

## 16) Phase 15 — observability

### Goal

Operators can see pause planning health and hold totals.

### Prerequisites

- Phase 8, 11 complete.

### Files modified

| File | Change |
|------|--------|
| `observability/tts.py` | Pause plan log/metric helpers |
| `observability/__init__.py` | Export helpers |
| `tts_pipeline/orchestrator/states.py` | Emit created/reused/latency from `plan_pauses` |
| `tts_pipeline/orchestrator/engine.py` | Emit `PausePlanFailed` on planner failure |
| `tests/tts/test_tts_observability.py` | Coverage |

### Checklist — events / metrics

- [x] `log_tts_pause_plan_created` → metric `PausePlanCreated`
- [x] `PausePlanReused`
- [x] `PausePlanFailed`
- [x] `PausePlanLatencyMs`
- [x] `PauseHoldSecondsTotal` (sum)
- [x] `PauseHoldCount`
- [x] Context fields: `audio_job_id`, `transcript_id`, `hold_count`, `total_hold_seconds`, `model`, `prompt_version`, `policy_version`

### Exit criteria

- [x] Logs filterable by `event_type` for pause planning (`pause_plan_created` / `reused` / `failed` / `latency`)
- [x] **Slice 4 observability half done**

**Phase 15 complete.**

## 17) Phase 16 — manifest and API surface

### Goal

Expose pause summary to operators without allowing caller-driven pause config.

### Prerequisites

- Phase 11 complete.

### Files modified

| File | Change |
|------|--------|
| `tts_pipeline/finalizer/manifest.py` | `pause_plan_summary` + metadata helper |
| `models/responses.py` | Optional status pause fields |
| `api/audio_service.py` | Map pause summary from job metadata |
| `tests/tts/test_manifest_finalizer.py` | Manifest summary coverage |
| `tests/tts/test_audio_api.py` | Status with/without pause metadata |

### Checklist — manifest JSON

- [x] `pause_plan_summary`: `{ hold_count, total_hold_seconds, policy_version, prompt_version }`
- [x] Do **not** require dumping full holds into public API if large — full plan stays in job metadata / debug

### Checklist — API

- [x] `AudioJobStatusResponse`: optional `pause_hold_count`, `pause_total_hold_seconds`
- [x] `POST /audio-jobs`: **no** new pause request fields in v1
- [x] Pre-feature jobs: fields null / omitted

### Checklist — tests

- [x] API test with metadata present
- [x] API test without pause metadata

### Exit criteria

- [x] **Slice 4 complete**

**Phase 16 complete. Slice 4 (Phases 15–16) complete.**

## 18) Phase 17 — operator smoke scripts

### Goal

Local validation without full AWS when possible.

### Prerequisites

- Phase 4, 9, 10 complete.

### Files created / modified

| File | Change |
|------|--------|
| `scripts/plan_pauses_smoke.py` **(new)** | File/beats → PausePlan JSON + holds table |
| `scripts/stitch_holds_smoke.py` **(new)** | Local MP3s + holds → `output/final-holds-smoke.mp3` |
| `scripts/run_tts_workflow_smoke.py` | Document `--start-at PlanPauses` / `MapPausesToChunks` |

### Checklist — `plan_pauses_smoke.py`

- [x] Args: `--text-file` or `--beats-file`, `--target-minutes`, `--out`
- [x] Calls real OpenAI when key present; `--dry-fixture` for offline
- [x] Prints holds table (index, seconds, kind, reason)

### Checklist — `stitch_holds_smoke.py`

- [x] Args: speech mp3s + holds file → `output/final-holds-smoke.mp3`
- [x] Optional: pipe into `mix_background_smoke.py` for listening

### Exit criteria

- [x] Operator can inspect pause quality before full pipeline cost

**Phase 17 complete.**

## 19) Phase 18 — E2E validation and listening QA

### Goal

Prove one full job feels like meditation, not a continuous lecture.

### Prerequisites

- Phase 13, 16, 17 complete.
- Background bed uploaded (Phase 18 of background-audio map) so holds are audible with music.
- **Deployed TTS worker must include pause planner** (see Phase 19). Dev worker last-checked (2026-07-07) predates pause planning — rebuild/apply before E2E.

### Operator helpers added

| File | Role |
|------|------|
| `scripts/pause_e2e_verify.py` | Automated metadata + duration checks; prints listening checklist |
| `scripts/run_full_pipeline.ps1` | Downloads `master.mp3` when present; prints `pause_plan_summary`; runs verify |

### Checklist — pipeline run

- [ ] Deploy pause-enabled TTS worker (Phase 19) if not already live
- [ ] Fresh transcript (avoid TTS job idempotency collision) or new version
- [ ] Delete stale `output/.pipeline_run.json` if using orchestrator resume
- [ ] Run `python -m pipeline_orchestrator` or `run_full_pipeline.ps1` (e.g. `-DurationMinutes 5`)
- [ ] Confirm job metadata contains `pause_plan` + `mapped_pause_plan` (`python scripts/pause_e2e_verify.py --audio-job-id <uuid> --final-mp3 ...`)
- [ ] Confirm `final.mp3` duration ≈ speech + holds
- [ ] Confirm `master.mp3` has bed present during holds

### Manual listening QA

- [ ] Short piece (~5–8 min): practice holds feel natural (not choppy)
- [ ] Medium (~10–12 min): at least one longer section/integration hold
- [ ] Hold after instruction: enough time to *do* the cue
- [ ] No spoken “pause” stage directions
- [ ] Bed continues during holds (not silence of everything)
- [ ] Closing integration hold ~30–60s when appropriate
- [ ] Retry same job: identical hold placement (idempotent)

### Exit criteria

- [ ] **Slice 5 E2E** signed off by listening, not only metrics

**Phase 18 blocked:** needs deploy + operator listening sign-off (helpers ready; do not mark complete until listening passes).

## 20) Phase 19 — rollout and documentation closeout

### Goal

Deploy safely and update project docs/rules.

### Prerequisites

- Phase 18 listening QA complete.

### Checklist — deploy

- [ ] Rebuild lambda zip (`scripts/build_lambda_package.py`)
- [ ] Terraform apply with required sensitive vars (do not apply bare)
- [ ] Confirm TTS worker + API get new code (pause planner runs in TTS worker path)
- [ ] Confirm OpenAI secret available to TTS worker role (IAM + env) — **may require infra change** if worker lacks model-provider secret today

### Checklist — infra verification (critical)

- [ ] Audit `infra/terraform/lambda_tts.tf` / IAM: does TTS worker already have OpenAI secret access?
- [ ] If **no**, add secret ARN env + `secretsmanager:GetSecretValue` in Phase 13/19 infra sub-checklist before enabling live planner
- [ ] Feature flag option (recommended): `CREATIVE_AGENT_PAUSE_PLANNER_ENABLED=true|false`  
  - [ ] When false: skip PlanPauses (empty plan) for emergency rollback without redeploying Agents

### Checklist — documentation

- [ ] Mark phases complete in this document
- [ ] Link from [`architecture-and-tts-plane.md`](architecture-and-tts-plane.md) “downstream concerns”
- [ ] Update [`.cursor/rules/project-context.mdc`](../.cursor/rules/project-context.mdc) build phase blurb (currently stale on TTS Phase 5)
- [ ] Cross-link from [`background-audio-mixing.md`](background-audio-mixing.md): holds make bed audible mid-piece

### Checklist — rollback

- [ ] Flag off → speech-only finals (legacy)
- [ ] Existing completed jobs remain valid
- [ ] No DB migration to reverse

### Exit criteria

- [ ] Dev smoke job green with flag on
- [ ] Flag-off rollback verified once
- [ ] Phase map closeout complete

---

## 21) Implementation notes — current code touchpoints

| Area | Current reality | Pause-plan implication |
|------|-----------------|------------------------|
| Workflow states | `LoadEnhancedTranscript` → `PlanChunks` → … → `FinalizeFinal` → `MixBackground` | Insert `PlanPauses` + `MapPausesToChunks` |
| Chunk planner | `plan_chunks_from_version` uses paragraphs/sentences | Mapping layer sits beside it; do not force planner to emit chunks |
| Stitch | `merge_mp3_chunks(list[bytes])` concat only | Add holds intercalation helper |
| Job metadata | `transcript_audio_job.metadata_json` JSONB | Store plans here — no migration |
| Enhanced content | `EnhancedScriptContent.beats` | Preferred planner anchors |
| Background mix | Sidechain ducking | No code change for holds |
| OpenAI in TTS worker | Verify IAM/env before Slice 3 prod enable | Likely infra prerequisite |

---

## 22) Suggested first PR slices (engineering)

1. **PR1 — Slice 1:** `tts_pipeline/pause_planner/` schema, policy, prompt, mocked client, anchors, tests.
2. **PR2 — Slice 2:** mapping, metadata service, silence generator, stitch intercalation, finalizer read of mapped plan, tests.
3. **PR3 — Slice 3:** workflow states + engine + feature flag + infra secret access if needed.
4. **PR4 — Slice 4:** metrics + manifest/API summary fields.
5. **PR5 — Slice 5:** smoke scripts + E2E listening notes + docs/rules update.

Do not start PR3 until PR2 can produce a local `final.mp3` with holds from fixture metadata (proves stitch without LLM flakiness).

---

## 23) Open questions (resolve before Phase 12 if possible)

| # | Question | Default if undecided |
|---|----------|----------------------|
| 1 | Fail job when OpenAI down, or empty plan fallback? | **Fail** (flag for empty fallback later) |
| 2 | Allow hold after final speech chunk? | **Yes** (silence then bed tail) |
| 3 | Same-chunk merged holds: sum or max? | **Sum**, then clamp |
| 4 | Which model? | `gpt-4o-mini` unless quality needs `gpt-4o` |
| 5 | Should `pipeline_orchestrator` display hold summary in logs? | Yes, log `hold_count` + `total_hold_seconds` |

---

## 24) Definition of done (feature complete)

- [ ] Phases 0–19 checkboxes complete
- [ ] Feature flag documented
- [ ] At least one production-like dev job listened end-to-end with bed + holds
- [ ] Idempotent retry demonstrated
- [ ] Rollback (flag off) demonstrated
- [ ] Master spec + this phase map marked complete
