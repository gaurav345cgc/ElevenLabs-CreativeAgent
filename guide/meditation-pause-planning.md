# Meditation Pause Planning — Implementation Guide

> **Status:** planned (not yet implemented)  
> **Authority:** Read after [`architecture-and-tts-plane.md`](architecture-and-tts-plane.md) and [`tts-plane-phase-map.md`](tts-plane-phase-map.md)  
> **Scope:** TTS plane — after enhanced transcript load, before/alongside chunk planning; silence realized at final stitch  
> **Related phase map:** [`meditation-pause-planning-phase-map.md`](meditation-pause-planning-phase-map.md)  
> **Upstream:** Agent 2 `ELEVENLABS_ENHANCED` · Downstream: chunk gen → stitch → background mix

This document is the **Cursor-ready product + architecture spec** for intentional meditation silence holds: voice stops so the listener can absorb and practice, while background bed continues.

**Authority rule:** Where this guide and the phase map disagree, **this guide wins**.

---

## 1) What we are building

After Agent 2 produces an `ELEVENLABS_ENHANCED` transcript, the TTS plane will:

1. Send the enhanced narration (beats / paragraphs) to an **OpenAI pause planner**.
2. Receive a structured **pause plan**: where to stop + how many seconds + reason.
3. Persist the plan on the audio job (idempotent, auditable).
4. Map holds onto TTS chunk boundaries.
5. Synthesize speech chunks with ElevenLabs as today (**spoken text unchanged**).
6. At stitch time, insert **silence audio** between speech chunks per the plan.
7. Run background mix as today — bed continues and becomes more audible during holds (ducking).

### Product outcome

| Before | After |
|--------|-------|
| Speech is nearly continuous; only micro punctuation pauses | Intentional practice holds and section rests |
| Bed has little “space” to breathe mid-piece | Bed carries the meditation during holds |
| Duration ≈ spoken words only | Duration = speech + holds + bed tail |
| Feels like a lecture with soft music | Feels like guided meditation |

### What this is *not*

- Not rewriting script meaning (Agent 1 / Agent 2 remain authoritative for words).
- Not asking ElevenLabs to speak “(pause 20 seconds)”.
- Not fading the bed out during holds.
- Not inserting silence after every sentence.
- Not changing the background-mix algorithm (it already fills narration silence).

---

## 2) Locked product decisions

| Decision | Choice |
|----------|--------|
| **Who decides where/how long** | OpenAI pause planner (dedicated LLM call) |
| **When planner runs** | After `LoadEnhancedTranscript`, before or immediately after `PlanChunks` — **before** ElevenLabs generation |
| **What planner returns** | Structured JSON pause plan only — **never** rewritten spoken text |
| **Anchor unit (v1)** | `after_beat_index` against Agent 2 `beats[]` when present; else paragraph index from `content_text` |
| **How silence is realized** | Insert generated silence MP3 between speech chunks at **FINALIZE_FINAL** stitch |
| **Bed during holds** | Existing sidechain mix — no special-case; bed naturally rises when voice is silent |
| **Silence counts toward duration** | Yes — advertised meditation length includes holds |
| **Caller API control** | None in v1 — server-side policy + planner only (mirror voice/background policy) |
| **Idempotency** | Persist pause plan on `transcript_audio_job.metadata_json`; reuse on retry |
| **Agent 2 change** | None required for v1 (optional later: Agent 2 emits hint beats) |
| **Transcript plane change** | **Forbidden** — do not redesign Agent 1 / Agent 2 / enhancement SQS |

---

## 3) Meditation hold model

### Hold kinds

| Kind | Typical length | When |
|------|----------------|------|
| **Practice hold** | 5–20s | After an instruction the listener must *do* |
| **Section rest** | 20–45s | Between major stages (settling → body → breath → mind → closing) |
| **Integration hold** | 30–60s | Before closing / deep rest (“about a minute”) |
| **Micro-pause** | < 2s | Punctuation / ElevenLabs natural — **not** planned by this feature |

v1 planner focuses on practice + section + integration holds. Micro-pauses stay with punctuation.

### Default policy ranges (prompt + hard clamps)

| Context | Default | Min clamp | Max clamp |
|---------|---------|-----------|-----------|
| After instruction cue | 10s | 5s | 20s |
| Between major sections | 25s | 15s | 45s |
| Before closing / integration | 45s | 30s | 90s |
| After final spoken line | 0s (use existing bed `tail_padding_ms`) | — | — |
| Single hold absolute max | — | — | **90s** |
| Minimum gap between holds | — | one intervening spoken beat preferred | — |

### Density rules

- Prefer holds after **imperatives / cues**, not after connective narration.
- Prefer **fewer longer holds** over many tiny ones.
- Cap total planned hold time so:  
  `estimated_speech_seconds + sum(holds) + tail ≈ target_duration_seconds`  
  (within a configurable tolerance, e.g. ±15%).

---

## 4) Pipeline placement

### Target workflow

```text
ValidateInput
  → CreateAudioJob
  → LoadEnhancedTranscript
  → PlanPauses            ← NEW (OpenAI pause planner)
  → PlanChunks
  → MapPausesToChunks     ← NEW (or folded into PlanChunks / PlanPauses exit)
  → PersistChunkPlan      ← also persist pause plan + mapped holds
  → GenerateChunksSequentially   ← speech only; no silence chunks sent to ElevenLabs
  → RegisterAssets
  → FinalizeFinal         ← stitch speech + insert silence per mapped holds
  → MixBackground         ← bed fills holds automatically
  → FinalizeManifest
  → MarkCompleted
  → Succeeded
```

### Artifact / data flow

```text
ELEVENLABS_ENHANCED (beats + content_text)
        ↓
  OpenAI pause planner
        ↓
  PausePlan (after_beat_index, hold_seconds, reason)
        ↓
  Chunk plan (speech chunks)
        ↓
  MappedPausePlan (after_chunk_index, hold_seconds, reason)
        ↓
  ElevenLabs MP3 chunks (voice only)
        ↓
  Stitch: chunk0 + silence + chunk1 + silence + ... → final.mp3
        ↓
  Mix: final.mp3 + bed → master.mp3
```

### Why not silence-as-TTS-chunk?

Sending empty/near-empty text to ElevenLabs is unreliable and wasteful. Silence is a **post-speech timeline** concern → generate with ffmpeg `anullsrc` / `aevalsrc=0` at stitch.

### Why not mix-only insertion?

Mix does not know meditation structure. Mid-script holds must live on the **narration timeline** so ducking, manifests, and duration estimates stay correct.

---

## 5) Pause plan schema (v1)

### Canonical model (conceptual)

```json
{
  "schema_version": "1.0",
  "planner": "openai",
  "model": "gpt-4o-mini",
  "target_duration_seconds": 600,
  "estimated_speech_seconds": 420,
  "total_hold_seconds": 140,
  "holds": [
    {
      "hold_id": "h1",
      "after_beat_index": 3,
      "hold_seconds": 12,
      "kind": "practice",
      "reason": "Listener needs time to soften shoulders"
    },
    {
      "hold_id": "h2",
      "after_beat_index": 11,
      "hold_seconds": 45,
      "kind": "integration",
      "reason": "Rest before closing"
    }
  ]
}
```

### Mapping after chunk planning

```json
{
  "schema_version": "1.0",
  "holds": [
    {
      "hold_id": "h1",
      "after_beat_index": 3,
      "after_chunk_index": 1,
      "hold_seconds": 12,
      "kind": "practice",
      "reason": "..."
    }
  ]
}
```

### Invariants

1. `after_beat_index` is `0..len(beats)-1` (hold occurs **after** that beat finishes).
2. Planner must not invent spoken text.
3. Hard clamp every `hold_seconds` into policy bounds.
4. Mapped `after_chunk_index` must reference an existing speech chunk.
5. Multiple holds mapping to the same chunk → **sum** or **max** (v1: **sum**, then re-clamp to max single-hold if needed — prefer merge with warning log).
6. No hold after the final chunk is required (bed tail handles end rest).

---

## 6) OpenAI planner contract

### Input

- Numbered beat list (preferred) or numbered paragraphs from `content_text`
- `target_duration_minutes` / seconds from transcript brief / job metadata
- Rough speech duration estimate (word count / existing duration estimate)
- Policy summary (min/max holds, kinds, density rules)
- Explicit instruction: **do not rewrite text**; return JSON only

### Output

- Strict JSON matching schema (use JSON mode / structured outputs)
- Temperature low (e.g. `0`–`0.3`) for stability
- Persist raw response + normalized plan for debugging

### Failure modes

| Failure | Behavior |
|---------|----------|
| OpenAI timeout / 5xx | Retry with backoff; then fail job (or optional policy: empty plan = speech-only — **v1 default: fail loudly**) |
| Invalid JSON / schema | Retry once with repair prompt; then fail |
| Holds out of range | Clamp + log warning |
| Duration budget blown | Scale holds down proportionally to fit budget; log |
| Empty beats and empty paragraphs | Skip planner; zero holds; log |

**v1 recommendation:** fail the audio job if planner fails — silent “no holds” fallback hides quality regressions. Optional later: `pause_policy.allow_empty_on_failure`.

---

## 7) Persistence

| Store | What |
|-------|------|
| `transcript_audio_job.metadata_json.pause_plan` | Normalized PausePlan |
| `transcript_audio_job.metadata_json.mapped_pause_plan` | After chunk mapping |
| `transcript_audio_event` | `PAUSE_PLAN_CREATED`, `PAUSE_PLAN_MAPPED`, `PAUSE_PLAN_CLAMPED` |
| Manifest JSON | Include `pause_plan` summary (total hold seconds, hold count) for operators |

No new Aurora table required for v1 (JSONB metadata is enough). Optional later: first-class `transcript_audio_pause` table if editing/replay tooling needs it.

Idempotency key consideration: pause plan is derived from `(transcript_version_id, pause_policy_version, planner_prompt_version)`. Store those versions in metadata. Re-running the same job reuses stored plan (do not re-call OpenAI unless `force_replan=true` / replay from `PlanPauses`).

---

## 8) Stitch realization

Current: `merge_mp3_chunks([c0, c1, c2, ...])` concatenates speech only.

New: build an interleaved list:

```text
[c0_bytes, silence(12s), c1_bytes, c2_bytes, silence(45s), c3_bytes, ...]
```

Silence generation (ffmpeg):

- Mono or stereo matching narration channel layout
- Same sample rate as re-encode target (stitch already re-encodes with `libmp3lame`)
- Generate once per distinct duration and cache in the temp workdir

Checksum / duration: `final.mp3` duration must include holds; manifest should report `total_hold_seconds` and `speech_only` vs `with_holds` if useful.

---

## 9) Interaction with background mix

No change to ducking math required.

Expected listening result:

- During speech → bed ducked
- During planned hold → bed more present (sidechain releases)
- After last word → existing `tail_padding_ms` bed outro

Manual QA must verify holds feel intentional, not like dropouts or dead air without bed.

---

## 10) Out of scope (v1)

- Caller-specified custom pause seconds via API
- Per-tenant pause profiles (can add later like voice profiles)
- SSML / ElevenLabs native break tags as primary mechanism
- Re-planning pauses without re-stitch (would need separate silence layer asset)
- Changing Agent 1 stage composition to insert hold markers
- Video / subtitle timing sync (future consumer of pause plan)

---

## 11) Success criteria

1. A 10-minute meditation includes audible mid-piece holds where voice stops and bed continues.
2. Spoken words never include pause stage directions.
3. Same transcript version + policy version → same pause plan on retry.
4. Manifest / job metadata shows hold count and total hold seconds.
5. Operators can replay from stitch with an existing plan without re-calling OpenAI.

---

## 12) Build entry point

Follow [`meditation-pause-planning-phase-map.md`](meditation-pause-planning-phase-map.md) from **Phase 0**.

Recommended first code slice: schema + OpenAI planner client + unit tests — **no workflow wiring** until mapping and stitch silence helpers exist.
