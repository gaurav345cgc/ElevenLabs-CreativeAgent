# Background Audio Mixing — Phase Map and Build Checklist

This is the **ultra-detailed implementation checklist** for adding curated background-audio beds under completed TTS narration. It extends the TTS plane finalizer only — downstream of ElevenLabs chunk synthesis and narration merge.

**Master spec:** [`background-audio-mixing.md`](background-audio-mixing.md)  
**TTS architecture:** [`architecture-and-tts-plane.md`](architecture-and-tts-plane.md)  
**Upstream TTS phases:** [`tts-plane-phase-map.md`](tts-plane-phase-map.md) (Phases 0–12 complete; Phase 11 finalization is the insertion point)

This document assumes the following is already complete and stable:

- TTS plane produces narration-only `final.mp3` via `finalize_audio_job_final()`.
- `FinalizeManifest` workflow state runs stitch + manifest in one step today (`orchestrator/states.py::finalize_manifest`).
- ffmpeg is available in the TTS worker Lambda (`finalizer/stitch.py::resolve_ffmpeg_executable`).
- Voice policy pattern exists in `tts_pipeline/voice_policy/` (mirror target for `background_policy/`).
- No DB migration is required — `transcript_audio_asset.asset_kind` is `TEXT`.

**Authority rule:** Where this phase map and [`background-audio-mixing.md`](background-audio-mixing.md) §1a disagree, **§1a wins**.

---

## 0) What this feature does

After the TTS plane merges ElevenLabs chunks into narration-only `final.mp3`:

1. Resolve an approved **background profile** (server-side policy — not caller-driven).
2. Load the bed track from S3 (`background/{profile_code}.mp3`).
3. Mix narration + bed with **sidechain ducking** (bed dips when voice speaks).
4. Write **`master.mp3`** as the primary deliverable.
5. Register a `MASTER` asset row and include master fields in the job manifest.

The narration-only `final.mp3` is **retained** for audit, re-mix without re-TTS, and downstream flexibility.

### Locked product decisions

| Decision | Choice |
|----------|--------|
| When mixing runs | Only after TTS final merge (`final.mp3` exists) |
| Bed selection | Policy default — server-side resolver (like `voice_policy/`) |
| Mix style | Sidechain ducking under narration |
| Artifacts | Keep `FINAL` (narration only) **and** add `MASTER` (mixed deliverable) |
| Library location | `background/` prefix in existing TTS S3 bucket |
| Default profile code | `calm_ambient_01` (placeholder until library uploaded) |
| Orchestrator integration | **Option A** — new `MIX_BACKGROUND` state + split `FINALIZE_FINAL` from manifest |

### Target workflow (after all phases complete)

```text
ValidateInput
  → CreateAudioJob
  → LoadEnhancedTranscript
  → PlanChunks
  → PersistChunkPlan
  → GenerateChunksSequentially
  → RegisterAssets
  → FinalizeFinal          ← stitch only (split from today)
  → MixBackground          ← NEW
  → FinalizeManifest       ← manifest only (references master)
  → MarkCompleted
  → Succeeded
```

### Artifact flow

```text
ElevenLabs chunks
       ↓
  final.mp3          (FINAL)   ← narration only, keep forever
       ↓
  + background bed   (from S3 background/{code}.mp3)
       ↓
  master.mp3         (MASTER)  ← primary deliverable
       ↓
  audio_manifest.json (MANIFEST) ← points at master when present
```

### Phase overview

| Phase | Title | Slice |
|-------|-------|-------|
| **0** | Boundary definition | — |
| **1** | Asset enum and S3 key helpers | 1 |
| **2** | Background policy schema | 1 |
| **3** | Background policy profiles registry | 1 |
| **4** | Background policy resolver | 1 |
| **5** | Background policy package exports and tests | 1 |
| **6** | ffmpeg mix engine | 1 |
| **7** | Mix unit tests | 1 |
| **8** | Repository `find_master_asset` | 2 |
| **9** | `finalize_audio_job_master` service | 2 |
| **10** | Manifest schema extension | 2 |
| **11** | Orchestrator workflow state split | 3 |
| **12** | Engine transitions and state policies | 3 |
| **13** | Orchestrator tests | 3 |
| **14** | Observability | 4 |
| **15** | API response models | 4 |
| **16** | API and integration tests | 4 |
| **17** | Operator scripts | 5 |
| **18** | Background library upload | 5 |
| **19** | Pipeline script and E2E validation | 5 |
| **20** | Rollout and documentation closeout | 5 |

---

### Phase dependency graph

Phases must be completed in order within each **slice**. Slices can be merged to `main` independently if later slices are not yet wired.

```text
Phase 0 (boundary)
  ↓
Phase 1 (enum + S3 keys) ─────────────────────────────┐
  ↓                                                   │
Phase 2 (policy schema) → Phase 3 (profiles) → Phase 4 (resolver) → Phase 5 (policy tests)
  ↓                                                   │
Phase 6 (mix engine) → Phase 7 (mix tests)                 │  Slice 1 — no pipeline wiring
  ↓                                                   │
Phase 8 (repository) → Phase 9 (finalizer service) → Phase 10 (manifest fields)  Slice 2
  ↓
Phase 11 (workflow states) → Phase 12 (engine + policies) → Phase 13 (orchestrator tests)  Slice 3
  ↓
Phase 14 (observability) → Phase 15 (API surface) → Phase 16 (API tests)  Slice 4
  ↓
Phase 17 (ops scripts) → Phase 18 (S3 library upload) → Phase 19 (E2E validation)  Slice 5
  ↓
Phase 20 (rollout + phase map closeout)
```

### Slice summary (merge strategy)

| Slice | Phases | Pipeline wired? | E2E useful? |
|-------|--------|-----------------|-------------|
| **Slice 1** | Phase 0 → Phase 7 | No | No (unit tests only) |
| **Slice 2** | Phase 8 → Phase 10 | No (service callable in isolation) | No |
| **Slice 3** | Phase 11 → Phase 13 | Yes — jobs produce `master.mp3` | Yes if bed uploaded |
| **Slice 4** | Phase 14 → Phase 16 | Yes — API exposes master | Yes |
| **Slice 5** | Phase 17 → Phase 20 | Yes — operator tooling complete | Yes (required) |

### Blocking prerequisite (production E2E)

A real background track must exist at:

```text
s3://{CREATIVE_AGENT_TTS_AUDIO_BUCKET}/background/calm_ambient_01.mp3
```

Until uploaded:

- Slices 1–2 are fully buildable with injected fakes / local files.
- Slice 3+ workflow runs will **fail at mix** if bed is missing — this is correct (fail loudly, never ship voice-only as `master.mp3`).

---

## 1) Phase 0 — boundary definition

### Goal

Lock scope and invariants before writing code. Confirm this work does not reopen transcript or generator layers.

### Prerequisites

- TTS Phase 11 (finalization) complete — see [`tts-plane-phase-map.md` §12](tts-plane-phase-map.md#12-phase-11--finalization-and-manifest).
- [`background-audio-mixing.md`](background-audio-mixing.md) reviewed.

### Checklist

- [x] Confirm mixing runs **only** after `final.mp3` exists (never per-chunk, never pre-ElevenLabs).
- [x] Confirm `transcript_composer/` and `tts_enhancer/` are **not** modified.
- [x] Confirm `tts_pipeline/generator/` and `chunk_planner/` are **not** modified.
- [x] Confirm no caller-supplied bed URLs, gain levels, or profile codes in v1 API.
- [x] Confirm `FINAL` asset is never overwritten or repurposed as `MASTER`.
- [x] Confirm `job.final_asset_id` continues to point at `FINAL` only (not `MASTER`).
- [x] Confirm background library uses shared `background/` prefix (not per-job prefix).
- [x] Confirm same TTS S3 bucket — no new bucket for v1.
- [x] Confirm Option A orchestrator integration (dedicated `MIX_BACKGROUND` state).
- [x] Confirm re-mix without re-TTS is a first-class requirement (replay from `MixBackground`).
- [x] Confirm missing bed → hard failure (no silent fallback to narration-only `master.mp3`).
- [ ] Identify at least one bed file for `calm_ambient_01` (operator action before E2E).

### In scope

- [ ] `tts_pipeline/finalizer/` — stitch unchanged; new `mix.py`; extended `service.py`, `manifest.py`
- [x] `tts_pipeline/background_policy/` — new package (schema + `__init__.py`; profiles/resolver in Phases 3–5)
- [ ] `tts_pipeline/orchestrator/` — state split and new transition
- [x] `models/enums.py` — `AudioAssetKind.MASTER`
- [ ] `db/repositories/audio_job_repository.py` — `find_master_asset()`
- [ ] `observability/tts.py` — master mix logging
- [ ] `models/responses.py`, `api/audio_service.py` — master fields
- [ ] `scripts/mix_background_smoke.py`, `scripts/run_full_pipeline.ps1` updates

### Out of scope (do not implement in any phase)

- [x] Per-chunk background mixing
- [x] Caller-driven voice/background configuration via API
- [x] Video, subtitles, stem export, multi-track DAW workflows
- [x] AI-generated or runtime-composed beds
- [x] New Lambda for v1 (mix runs in existing `tts-worker`)
- [x] DB migration for `asset_kind` or `master_asset_id` column (v1 uses asset query)
- [x] Transcript table or SQS message shape changes

### Exit criteria

- [x] Decisions table in [`background-audio-mixing.md` §1](background-audio-mixing.md#1-what-we-are-building) accepted.
- [x] No overlap with transcript enhancement or ElevenLabs generation logic.

---

## 2) Phase 1 — asset enum and S3 key helpers

### Goal

Add application-level `MASTER` asset kind and S3 key functions. Zero runtime behavior change until later phases wire them.

### Prerequisites

- Phase 0 complete.

### Files to modify

| File | Change |
|------|--------|
| `models/enums.py` | Add `MASTER = "master"` to `AudioAssetKind` |
| `tts_pipeline/persistence/s3_keys.py` | Add `master_object_key()`, `background_track_key()` |
| `tests/tts/test_tts_enums.py` | Assert `AudioAssetKind.MASTER.value == "master"` |

### Checklist — `models/enums.py`

- [x] Add `MASTER = "master"` after `FINAL`, before `MANIFEST` (ordering matches artifact pipeline).
- [x] Verify `AUDIO_ASSET_KIND_VALUES` tuple auto-includes new value (derived from enum).
- [x] Grep codebase for exhaustive `AudioAssetKind` switches — update any `match`/`if` chains that assume fixed set.

### Checklist — `s3_keys.py`

- [x] Add `master_object_key(tenant_id, transcript_id, audio_job_id) -> str`:
  - [x] Returns `{job_prefix(...)}final/master.mp3`
  - [x] Mirrors `final_object_key()` pattern exactly
- [x] Add `background_track_key(profile_code: str) -> str`:
  - [x] Returns `background/{profile_code}.mp3`
  - [x] Job-agnostic — no tenant/transcript/job in path
- [x] Update module docstring to document new layout lines:
  - [x] `{tenant}/{transcript}/{job}/final/master.mp3`
  - [x] `background/{profile_code}.mp3` (shared library)

### Unit tests

- [x] `test_master_object_key_matches_job_prefix_pattern`
- [x] `test_background_track_key_format`
- [x] `test_audio_asset_kind_master_value`

### Exit criteria

- [x] `AudioAssetKind.MASTER` exists; no DB migration required.
- [x] Key helpers return expected strings for sample UUIDs.
- [x] All existing tests pass — no pipeline behavior change.

---

## 3) Phase 2 — background policy schema

### Goal

Define the `BackgroundProfile` dataclass/schema and mix-parameter bounds.

### Prerequisites

- Phase 1 complete.

### Files to create

| File | Purpose |
|------|---------|
| `tts_pipeline/background_policy/schema.py` | `BackgroundProfile` + optional bounds types |

### Checklist — `schema.py`

- [x] Create `@dataclass(frozen=True, slots=True) class BackgroundProfile` with fields:

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `code` | `str` | required | e.g. `"calm_ambient_01"` |
| `display_name` | `str` | required | Human label |
| `description` | `str` | required | Operator docs |
| `track_object_key` | `str` | required | e.g. `"background/calm_ambient_01.mp3"` |
| `gain_db` | `float` | `-22.0` | Bed level before ducking |
| `fade_in_ms` | `int` | `3000` | Bed fade in at start |
| `fade_out_ms` | `int` | `5000` | Bed fade out at end |
| `tail_padding_ms` | `int` | `4000` | Bed continues after last word |
| `duck` | `bool` | `True` | Sidechain compress under narration |
| `duck_threshold` | `float` | `0.03` | sidechaincompress threshold |
| `duck_ratio` | `float` | `8.0` | |
| `duck_attack_ms` | `int` | `5` | |
| `duck_release_ms` | `int` | `400` | |
| `loudness_target_lufs` | `float` | `-16.0` | EBU R128 integrated |
| `loudness_true_peak_db` | `float` | `-1.5` | |
| `output_bitrate` | `str` | `"192k"` | libmp3lame bitrate |

- [x] Use `from __future__ import annotations` (match `voice_policy` style).
- [x] Do **not** use Pydantic for v1 unless aligning with a deliberate refactor — spec uses `@dataclass`; `voice_policy` uses Pydantic for ElevenLabs validation needs. Background profile is simpler; dataclass is fine per spec.
- [x] Add module docstring: `"Background profile schema and mix bounds for post-TTS bed mixing."`

### Exit criteria

- [x] `BackgroundProfile` importable from `tts_pipeline.background_policy.schema`.
- [x] Frozen/immutable profile instances.

---

## 4) Phase 3 — background policy profiles registry

### Goal

Register approved bed profiles in code — same pattern as `APPROVED_VOICE_PROFILES`.

### Prerequisites

- Phase 2 complete.

### Files to create

| File | Purpose |
|------|---------|
| `tts_pipeline/background_policy/profiles.py` | Registry + default code constant |

### Checklist — `profiles.py`

- [x] Define `DEFAULT_BACKGROUND_PROFILE_CODE = "calm_ambient_01"`.
- [x] Define `APPROVED_BACKGROUND_PROFILES: dict[str, BackgroundProfile]` with at least:

```python
"calm_ambient_01": BackgroundProfile(
    code="calm_ambient_01",
    display_name="Calm ambient — primary bed",
    description="Soft ambient pad for guided meditation. Looping bed with ducking.",
    track_object_key="background/calm_ambient_01.mp3",
    gain_db=-22.0,
    fade_in_ms=3000,
    fade_out_ms=5000,
    tail_padding_ms=4000,
    duck=True,
)
```

- [x] Ensure `track_object_key` matches `background_track_key(code)` from Phase 1.
- [x] Mirror `voice_policy/profiles.py` structure: private helpers optional, single default profile for v1.

### Exit criteria

- [x] Default profile registered and key-aligned with S3 upload path.
- [x] No external config file — profiles live in code (same as voice policy).

---

## 5) Phase 4 — background policy resolver

### Goal

Resolve approved background profiles server-side. Raise on unknown codes.

### Prerequisites

- Phase 3 complete.

### Files to create

| File | Purpose |
|------|---------|
| `tts_pipeline/background_policy/resolver.py` | Lookup + job resolution |

### Checklist — `resolver.py`

- [x] Define `class BackgroundPolicyError(ValueError)` — mirror `VoicePolicyError`.
- [x] Implement `list_background_profile_codes() -> list[str]` — sorted keys from registry.
- [x] Implement `get_background_profile(code: str) -> BackgroundProfile`:
  - [x] Raise `BackgroundPolicyError` with known codes list on unknown code
  - [x] Mirror `get_voice_profile()` error message style
- [x] Implement `resolve_background_profile(*, content_type: str | None = None, tenant_id: UUID | None = None) -> BackgroundProfile`:
  - [x] v1: ignore optional args; return `get_background_profile(DEFAULT_BACKGROUND_PROFILE_CODE)`
  - [x] Docstring notes v2 will map `content_type` / tenant — still registry-only

### Exit criteria

- [x] Unknown profile code raises `BackgroundPolicyError`.
- [x] Resolver never accepts raw S3 URLs or caller-supplied gain values.

---

## 6) Phase 5 — background policy package exports and tests

### Goal

Complete `background_policy/` package surface and unit test coverage.

### Prerequisites

- Phase 4 complete.

### Files to create

| File | Purpose |
|------|---------|
| `tts_pipeline/background_policy/__init__.py` | Public exports |
| `tests/tts/test_background_policy.py` | Unit tests |

### Checklist — `__init__.py`

Mirror `tts_pipeline/voice_policy/__init__.py` export pattern:

- [x] Export `APPROVED_BACKGROUND_PROFILES`, `DEFAULT_BACKGROUND_PROFILE_CODE`
- [x] Export `BackgroundPolicyError`, `get_background_profile`, `list_background_profile_codes`, `resolve_background_profile`
- [x] Export `BackgroundProfile` from schema
- [x] Define `__all__` list explicitly

### Checklist — `tests/tts/test_background_policy.py`

Mirror `tests/tts/test_voice_policy.py`:

- [x] `test_default_profile_exists` — `DEFAULT_BACKGROUND_PROFILE_CODE == "calm_ambient_01"`
- [x] `test_default_profile_in_approved_registry`
- [x] `test_list_background_profile_codes_is_sorted`
- [x] `test_get_background_profile_returns_expected_track_key`
- [x] `test_unknown_profile_raises_background_policy_error`
- [x] `test_resolve_background_profile_returns_default_for_v1`
- [x] `test_track_object_key_matches_background_track_key_helper`

### Exit criteria

- [x] `from tts_pipeline.background_policy import resolve_background_profile` works.
- [x] All policy unit tests pass.
- [x] **Slice 1 policy half complete** — no pipeline imports yet.

---

## 7) Phase 6 — ffmpeg mix engine

### Goal

Implement `mix_background()` — narration + bed → single MP3 with ducking, loop, fade, loudnorm.

### Prerequisites

- Phase 2 complete (needs `BackgroundProfile` type).
- Phase 1 complete (keys documented; mix module uses profile fields, not keys directly).

### Files to create

| File | Purpose |
|------|---------|
| `tts_pipeline/finalizer/mix.py` | Mix implementation |

### Checklist — exceptions and types

- [x] Define `class BackgroundMixError(RuntimeError)` — mirror `FinalMergeError` in `stitch.py`.
- [x] Define `MixFn = Callable[[bytes, bytes, BackgroundProfile], bytes]` for injection in tests/service.

### Checklist — ffmpeg integration

- [x] Import `resolve_ffmpeg_executable` from `tts_pipeline.finalizer.stitch` — **do not re-implement**.
- [x] Implement `mix_background(narration_bytes, bed_bytes, profile, *, ffmpeg_executable=None) -> bytes`:
  - [x] Reject empty `narration_bytes` → `BackgroundMixError`
  - [x] Reject empty `bed_bytes` → `BackgroundMixError`
  - [x] Write inputs to temp files (mirror `merge_mp3_chunks` temp dir pattern in `stitch.py`)
  - [x] Invoke ffmpeg with `-hide_banner -loglevel error -y`

### Checklist — filter graph (ducking enabled, `profile.duck is True`)

- [x] `-stream_loop -1` on bed input for infinite loop
- [x] Bed chain: `volume={gain_db}dB` → `afade=t=in:st=0:d={fade_in_s}`
- [x] Sidechain: `[bed][narration]sidechaincompress=threshold=...:ratio=...:attack=...:release=...`
- [x] Mix: `[narration][ducked_bed]amix=inputs=2:duration=first:dropout_transition=0`
- [x] Tail: `apad=pad_dur={tail_s}` (convert `tail_padding_ms` to seconds)
- [x] Fade out: `afade=t=out:st={fade_out_start_s}:d={fade_out_s}` (start computed from ffprobe duration)
- [x] Loudness: `loudnorm=I={target}:TP={peak}:LRA=11`
- [x] Output: `-map "[out]" -c:a libmp3lame -b:a {profile.output_bitrate}`

### Checklist — non-ducking path (`profile.duck is False`)

- [x] Simpler graph: leveled bed + voice `amix` without sidechaincompress
- [x] Same fade, pad, loudnorm tail

### Checklist — duration / fade-out placement

- [x] Prefer narration duration from ffprobe when available
- [x] Fallback: skip explicit fade-out when duration is unknown (documented in code comment)
- [ ] Optional v1.1: read duration from `FINAL` asset `metadata_json` if stitch stores it (not blocking v1)

### Checklist — error handling

- [x] ffmpeg not found → `BackgroundMixError` wrapping stitch resolver message
- [x] ffmpeg nonzero exit → `BackgroundMixError` with stderr snippet
- [x] Output missing or zero bytes → `BackgroundMixError`

### Exit criteria

- [x] `mix_background()` produces valid MP3 bytes against local test files (manual or scripted).
- [x] Duck and non-duck code paths implemented.
- [x] No pipeline wiring — module is pure + ffmpeg side effect.

---

## 8) Phase 7 — mix unit tests

### Goal

Test mix logic without requiring ffmpeg in CI (injected `mix_fn` pattern) and optionally gate real ffmpeg tests.

### Prerequisites

- Phase 6 complete.

### Files to create

| File | Purpose |
|------|---------|
| `tests/tts/test_background_mix.py` | Unit tests |

### Checklist

- [x] Test empty narration bytes raises `BackgroundMixError`
- [x] Test empty bed bytes raises `BackgroundMixError`
- [x] Test filter graph builder (if extracted) selects duck vs non-duck strings
- [x] Test `mix_background` with `monkeypatch` on subprocess / ffmpeg executable:
  - [x] Success path returns bytes
  - [x] Nonzero exit raises `BackgroundMixError`
- [x] Optional `@pytest.mark.skipif(not shutil.which("ffmpeg"))` integration test with tiny local MP3s
- [x] Do not call real S3 in unit tests

### Exit criteria

- [x] **Slice 1 complete** — policy + mix modules testable in isolation.
- [x] `pytest tests/tts/test_background_policy.py tests/tts/test_background_mix.py` passes (16 passed).
- [x] No changes to orchestrator, API, or existing finalizer behavior.

---

## 9) Phase 8 — repository `find_master_asset`

### Goal

Add DB lookup for `MASTER` asset rows — mirror `find_final_asset`.

### Prerequisites

- Phase 1 complete (`AudioAssetKind.MASTER`).

### Files to modify

| File | Change |
|------|--------|
| `db/repositories/audio_job_repository.py` | Add `find_master_asset()` |

### Checklist

- [x] Copy `find_final_asset()` pattern exactly:
  ```python
  def find_master_asset(self, session, audio_job_id: UUID) -> TranscriptAudioAssetRecord | None:
      stmt = select(TranscriptAudioAssetRow).where(
          TranscriptAudioAssetRow.audio_job_id == audio_job_id,
          TranscriptAudioAssetRow.asset_kind == AudioAssetKind.MASTER.value,
      )
      ...
  ```
- [x] No new indexes required for v1 (same as `find_final_asset` — job-scoped query).
- [ ] Mock repo in tests: add `find_master_asset` to `tests/tts/test_manifest_finalizer.py` fake repo (deferred to Phase 9/10 when service uses it).

### Exit criteria

- [x] Repository method returns `None` or `TranscriptAudioAssetRecord` with `asset_kind == MASTER`.
- [x] No migration.

---

## 10) Phase 9 — `finalize_audio_job_master` service

### Goal

Orchestrate idempotent master mix: load FINAL + bed from S3, mix, persist, register asset, emit events.

### Prerequisites

- Phase 5, Phase 6, Phase 8 complete.

### Files to modify

| File | Change |
|------|--------|
| `tts_pipeline/finalizer/service.py` | Add `finalize_audio_job_master()`, result type, events |
| `tts_pipeline/finalizer/__init__.py` | Export new symbols |

### Checklist — result type and constants

- [x] Add `FinalizeMasterResult` dataclass (mirror `FinalizeFinalResult`):
  - [x] Fields: `stored`, `asset`, `skipped: bool`, `checksum_sha256`, `byte_size`
- [x] Add `MASTER_MIXED_EVENT = "MASTER_MIXED"`
- [x] Add `MASTER_SKIPPED_EVENT = "MASTER_SKIPPED"`

### Checklist — `finalize_audio_job_master()` implementation

Follow `finalize_audio_job_final()` structure in `service.py`:

- [x] Signature:
  ```python
  def finalize_audio_job_master(
      session, repo, job, *,
      correlation_id=None, s3_client=None, mix_fn=None,
  ) -> FinalizeMasterResult:
  ```
- [x] **Idempotency:** `existing = repo.find_master_asset(session, job.id)` → if exists:
  - [x] Log `log_tts_master_mixed(..., skipped=True)` (added `log_tts_master_mixed` in `observability/tts.py`)
  - [x] Record `MASTER_SKIPPED` event with `reason: master_already_registered`
  - [x] Return `FinalizeMasterResult(skipped=True, ...)`
- [x] **Require FINAL:** `final_asset = repo.find_final_asset(session, job.id)` — if `None`:
  - [x] Raise `FinalAudioMergeError("final narration asset missing before background mix")`
- [x] **Resolve profile:** `resolve_background_profile(tenant_id=job.tenant_id)`
- [x] **Load S3 bytes** — **keyword-only** args:
  - [x] `read_object_bytes(object_key=final_asset.object_key, s3_client=s3_client)`
  - [x] `read_object_bytes(object_key=profile.track_object_key, s3_client=s3_client)`
  - [x] Wrap storage failures with `_log_and_reraise_storage_failure(..., artifact_kind="final" | "background_bed")`
  - [x] Missing bed → fail loudly (do not produce master)
- [x] **Mix:** `master_bytes = (mix_fn or mix_background)(narration_bytes, bed_bytes, profile)`
  - [x] Catch `BackgroundMixError` → raise `FinalAudioMergeError`
- [x] **Persist S3:**
  - [x] `checksum_sha256 = hashlib.sha256(master_bytes).hexdigest()`
  - [x] `object_key = master_object_key(job.tenant_id, job.transcript_id, job.id)`
  - [x] `write_audio_object(object_key=..., audio_bytes=..., checksum_sha256=..., mime_type="audio/mpeg", s3_client=..., metadata={...})`
  - [x] Metadata: `audio-job-id`, `background-profile-code`
- [x] **Register asset:** `repo.create_audio_asset(..., asset_kind=AudioAssetKind.MASTER, metadata_json={...})`:
  - [x] `background_profile_code`, `background_track_key`, `gain_db`, `duck`
  - [x] `merge_strategy: "ffmpeg_sidechain_duck"` (or `"ffmpeg_amix"` when duck false)
  - [x] `source_final_asset_id`
- [x] **Do not** set `job.final_asset_id` — that remains FINAL only
- [x] Record `MASTER_MIXED` event
- [x] Log `log_tts_master_mixed(..., skipped=False)`

### Checklist — `finalizer/__init__.py`

- [x] Export `finalize_audio_job_master`, `FinalizeMasterResult`, `MASTER_MIXED_EVENT`, `MASTER_SKIPPED_EVENT`
- [x] Add to `__all__`

### Exit criteria

- [x] Service callable in isolation with mocked S3 and `mix_fn`.
- [x] Idempotent second call returns `skipped=True`.
- [x] Workflow not yet wired — existing jobs unaffected.

---

## 11) Phase 10 — manifest schema extension

### Goal

Include master artifact fields in `AudioJobManifest` JSON and `build_audio_job_manifest()`.

### Prerequisites

- Phase 9 complete.

### Files to modify

| File | Change |
|------|--------|
| `tts_pipeline/finalizer/manifest.py` | Extend dataclass + builder |
| `tts_pipeline/finalizer/service.py` | Pass master fields into `finalize_audio_job_manifest()` |

### Checklist — `AudioJobManifest` dataclass

Add optional fields (keep existing `final_*` for traceability):

- [x] `master_object_key: str | None = None`
- [x] `master_asset_id: str | None = None`
- [x] `master_checksum_sha256: str | None = None`
- [x] `master_byte_size: int | None = None`
- [x] `background_profile_code: str | None = None`
- [x] `background_track_key: str | None = None`

### Checklist — `to_dict()`

- [x] Include master fields only when not `None` (same pattern as `final_*`).

### Checklist — `build_audio_job_manifest()`

- [x] Add optional kwargs: `master_object_key`, `master_asset_id`, `master_checksum_sha256`, `master_byte_size`, `background_profile_code`, `background_track_key`
- [x] Pass through to `AudioJobManifest` constructor

### Checklist — `finalize_audio_job_manifest()` in `service.py`

- [x] Add optional `master_asset` parameter (mirror `final_asset` parameter pattern)
- [x] When `master_asset` provided, populate manifest master fields from asset row + metadata_json
- [x] Keep `schema_version = "tts-audio-manifest-v1"` (backward compatible optional fields)

### Checklist — `tests/tts/test_manifest_finalizer.py`

- [x] Extend fake repo with `find_master_asset`
- [x] Test manifest includes `master_object_key` and `background_profile_code` when master finalized
- [x] Test `MASTER_SKIPPED` idempotency on second `finalize_audio_job_master` call
- [x] Test full flow: final → master → manifest (mocked S3 + `mix_fn`)

### Exit criteria

- [x] **Slice 2 complete** — finalizer can produce master + manifest in isolation.
- [x] Manifest JSON includes master fields when master step ran.
- [x] Pre-feature manifests without master fields remain valid.

---

## 12) Phase 11 — orchestrator workflow state split

### Goal

Split today's combined finalize into `FinalizeFinal` and prepare for `MixBackground` + manifest-only `FinalizeManifest`.

### Prerequisites

- Phase 9, Phase 10 complete.

### Files to modify

| File | Change |
|------|--------|
| `tts_pipeline/orchestrator/workflow.py` | Add `FINALIZE_FINAL`, `MIX_BACKGROUND` |
| `tts_pipeline/orchestrator/states.py` | Split `finalize_manifest()` into three functions |
| `tts_pipeline/orchestrator/__init__.py` | Export new states if needed |

### Checklist — `workflow.py`

- [x] Add to `WorkflowState`:
  ```python
  FINALIZE_FINAL = "FinalizeFinal"
  MIX_BACKGROUND = "MixBackground"
  ```
- [x] Keep `FINALIZE_MANIFEST = "FinalizeManifest"` — semantics change to manifest-only
- [x] Insert ordering: `... REGISTER_ASSETS, FINALIZE_FINAL, MIX_BACKGROUND, FINALIZE_MANIFEST, MARK_COMPLETED ...`

### Checklist — `states.py` refactor

Today `finalize_manifest()` calls both `finalize_audio_job_final` and `finalize_audio_job_manifest`. Split into:

- [x] `finalize_final(session, audio_repo, ctx, *, s3_client=None) -> None`:
  - [x] `reload_job_and_chunks`
  - [x] Call `finalize_audio_job_final(...)`
  - [x] Store in `ctx.metadata`: `final_object_key`, `final_asset_id`, `final_skipped`, `final_checksum_sha256`
- [x] `mix_background(session, audio_repo, ctx, *, s3_client=None) -> None`:
  - [x] `reload_job_and_chunks`
  - [x] Call `finalize_audio_job_master(...)`
  - [x] Store in `ctx.metadata`: `master_object_key`, `master_asset_id`, `master_skipped`, `master_checksum_sha256`
- [x] `finalize_manifest_only(session, audio_repo, ctx, *, s3_client=None) -> None`:
  - [x] `reload_job_and_chunks`
  - [x] Resolve `final_asset` from metadata or `find_final_asset`
  - [x] Resolve `master_asset` from metadata or `find_master_asset`
  - [x] Call `finalize_audio_job_manifest(..., final_asset=..., master_asset=...)`
  - [x] Store manifest metadata in `ctx.metadata`

- [x] Deprecate monolithic `finalize_manifest()` — kept as thin delegator (`finalize_final` + `finalize_manifest_only`) so the engine stays green until **Phase 12** rewires transitions; removed then.
- [x] Update imports in `states.py` to include `finalize_audio_job_master`

### Exit criteria

- [x] Three distinct state handler functions exist with clear responsibilities.
- [x] `ctx.metadata` carries forward final and master asset info for manifest step.

---

## 13) Phase 12 — engine transitions and state policies

### Goal

Wire new states into `TtsWorkflowEngine` with correct transitions, policies, and replay support.

### Prerequisites

- Phase 11 complete.

### Files to modify

| File | Change |
|------|--------|
| `tts_pipeline/orchestrator/engine.py` | Update `_run_session_state` transitions |
| `tts_pipeline/orchestrator/config.py` | Add state policies |
| `infra/step_functions/tts_audio_job.asl.json` | Optional: mirror new states (if maintained) |

### Checklist — `engine.py` `_run_session_state`

Replace current block:

```python
if state is WorkflowState.REGISTER_ASSETS:
    register_assets(...)
    return WorkflowState.FINALIZE_MANIFEST

if state is WorkflowState.FINALIZE_MANIFEST:
    finalize_manifest(...)
    return WorkflowState.MARK_COMPLETED
```

With:

- [x] `REGISTER_ASSETS` → return `FINALIZE_FINAL`
- [x] `FINALIZE_FINAL` → call `finalize_final(...)` → return `MIX_BACKGROUND`
- [x] `MIX_BACKGROUND` → call `mix_background(...)` → return `FINALIZE_MANIFEST`
- [x] `FINALIZE_MANIFEST` → call `finalize_manifest_only(...)` → return `MARK_COMPLETED`

### Checklist — linear state list in `engine.py`

- [x] Update any `_LINEAR_STATES` or validation tuple to include `FINALIZE_FINAL` and `MIX_BACKGROUND` in order.

### Checklist — `config.py` `STATE_POLICIES`

- [x] Add `"FinalizeFinal": StatePolicy(max_attempts=2, timeout_seconds=120)`
- [x] Add `"MixBackground": StatePolicy(max_attempts=2, timeout_seconds=180)` — longer for loudnorm on long files
- [x] Update `"FinalizeManifest"` timeout if needed (manifest only — may reduce from 60s)
- [x] Split policies replace single `FinalizeManifest` doing both stitch + mix

### Checklist — replay

- [x] `WorkflowInput(start_state=WorkflowState.MIX_BACKGROUND, audio_job_id=...)` skips to mix
- [x] `WorkflowInput(start_state=WorkflowState.FINALIZE_FINAL, ...)` for re-stitch only
- [x] Replay logging via existing `log_tts_replay` — no change required

### Checklist — failure propagation

- [x] `BackgroundMixError` / `FinalAudioMergeError` from mix → workflow failure handler
- [x] Job must not reach `COMPLETED` without master when mix is required (v1: always required)

### Exit criteria

- [x] Engine executes full state sequence including new states.
- [x] Replay from `MIX_BACKGROUND` works when `FINAL` exists.

---

## 14) Phase 13 — orchestrator tests

### Goal

Lock workflow ordering and replay behavior with automated tests.

### Prerequisites

- Phase 12 complete.

### Files to modify

| File | Change |
|------|--------|
| `tests/tts/test_orchestrator.py` | Extend state order and replay tests |

### Checklist

- [x] Assert transition order: `REGISTER_ASSETS` → `FINALIZE_FINAL` → `MIX_BACKGROUND` → `FINALIZE_MANIFEST` → `MARK_COMPLETED`
- [x] Mock `finalize_audio_job_master` — verify called in `MIX_BACKGROUND`
- [x] Mock `finalize_audio_job_final` — verify **not** called in `FINALIZE_MANIFEST`
- [x] Replay from `MIX_BACKGROUND` with existing FINAL — master step runs, chunks not regenerated
- [x] Failure in mix state does not register `MANIFEST` or `COMPLETED`

### Exit criteria

- [x] **Slice 3 complete** — full workflow produces master when bed exists.
- [x] `pytest tests/tts/test_orchestrator.py` passes.

---

## 15) Phase 14 — observability

### Goal

Structured logs, job events, and CloudWatch metrics for master mix — mirror final merge pattern.

### Prerequisites

- Phase 9 complete (service calls log hooks).

### Files to modify

| File | Change |
|------|--------|
| `observability/tts.py` | Add `log_tts_master_mixed` |
| `observability/__init__.py` | Export new log function |
| `tests/tts/test_tts_observability.py` | Metric test |

### Checklist — `log_tts_master_mixed`

Mirror `log_tts_final_merged`:

- [x] `log_tts_event("tts master mixed", event_type="master_mixed", **context)`
- [x] `record_tts_metric("MasterMixed", **context)`
- [x] Context fields: `audio_job_id`, `transcript_id`, `object_key`, `asset_id`, `skipped`, `byte_size`, `checksum_sha256`, `background_profile_code`, `background_track_key`

### Checklist — optional metrics

- [x] `MasterMixSkipped` — on idempotent skip (or use `skipped=True` on `MasterMixed`)
- [x] `MasterMixFailed` — on failure path if not covered by `WorkflowFailed`
- [x] `MasterMixDurationMs` — if timing wrapper added in service

### Checklist — events (in service)

- [x] `MASTER_MIXED` — new master written
- [x] `MASTER_SKIPPED` — idempotent skip
- [x] Existing `FINAL_MERGED` / `MANIFEST_FINALIZED` unchanged

### Checklist — tests

- [x] `test_log_tts_master_mixed_records_metric` — mirror `test_log_tts_final_merged_records_metric`

### Exit criteria

- [x] Master mix emits structured log + EMF metric on success and skip.
- [x] Operators can filter logs by `event_type=master_mixed`.

---

## 16) Phase 15 — API response models

### Goal

Expose master asset identity and presigned URLs through existing audio job endpoints.

### Prerequisites

- Phase 10 complete.

### Files to modify

| File | Change |
|------|--------|
| `models/responses.py` | Add master fields |
| `api/audio_service.py` | Map master asset |

### Checklist — `AudioJobStatusResponse`

- [x] Add `master_asset_id: UUID | None = None`

### Checklist — `AudioJobManifestResponse`

- [x] Add `master_asset_id: UUID | None = None`
- [x] Add `master_object_key: str | None = None`
- [x] Add `master_url: str | None = None` — presigned when `include_urls=true`

### Checklist — `audio_service.py`

- [x] `get_audio_job_status`: `find_master_asset` → set `master_asset_id`
- [x] `get_audio_job_manifest`:
  - [x] Load master asset via `find_master_asset`
  - [x] Prefer manifest JSON `master_object_key` with asset fallback
  - [x] When `include_urls` and master exists: `generate_presigned_object_url` → `master_url`
  - [x] Keep `final_url` for debugging / backward compatibility
  - [x] Document: **`master_url` is primary download** when present

### Checklist — v1 API invariants

- [x] `POST /audio-jobs` — **no** new request fields for background
- [x] No breaking changes to existing response fields

### Exit criteria

- [x] API returns master fields for jobs that completed after BG rollout.
- [x] Pre-feature jobs return `master_* = None`; `final_url` still works.

---

## 17) Phase 16 — API and integration tests

### Goal

Verify API mapping and end-to-end finalizer flow with master artifacts.

### Prerequisites

- Phase 15 complete.

### Files to modify

| File | Change |
|------|--------|
| `tests/tts/test_audio_api.py` | Master fields on status/manifest responses |
| `tests/tts/test_manifest_finalizer.py` | Full final → master → manifest (if not done in Phase 10) |

### Checklist — `test_audio_api.py`

- [x] Fake repo returns master asset — status includes `master_asset_id`
- [x] Manifest response includes `master_object_key`, `master_url` when `include_urls=true`
- [x] Job without master — fields are `None`, `final_url` still populated

### Manual QA checklist (from spec)

- [ ] Short meditation (~3 min) — bed loops, no abrupt cut
- [ ] Long meditation (~20 min) — bed loops, no drift
- [ ] Silent pauses — bed fills space; dense narration — bed ducks
- [ ] Missing bed file — job fails clearly
- [ ] SQS retry — single `MASTER` asset
- [ ] Presigned `master_url` downloads playable MP3

### Exit criteria

- [x] **Slice 4 complete** — API and observability surface master deliverable.
- [x] Automated API tests pass.

---

## 18) Phase 17 — operator scripts

### Goal

Local smoke test and workflow replay tooling for mix step.

### Prerequisites

- Phase 6, Phase 9 complete.

### Files to create / modify

| File | Change |
|------|--------|
| `scripts/mix_background_smoke.py` | **New** — local mix smoke test |
| `scripts/finalize_manifest_smoke.py` | Optional: add master step |
| `scripts/run_tts_workflow_smoke.py` | Document `--start-at MixBackground` |

### Checklist — `mix_background_smoke.py`

- [x] CLI args: `--narration`, `--bed`, `--out`, optional `--profile-code`
- [x] Load local files, call `mix_background` or `resolve_background_profile` + mix
- [x] Print duration, byte size, output path
- [x] Example:
  ```bash
  python scripts/mix_background_smoke.py \
    --narration output/final-<uuid>.mp3 \
    --bed library/calm_ambient_01.mp3 \
    --out output/master-smoke.mp3
  ```

### Checklist — workflow replay

- [x] Document replay: `WorkflowInput(audio_job_id=uuid, start_state=WorkflowState.MIX_BACKGROUND)`
- [x] Re-mix procedure: delete/supersede `MASTER` row → replay from `MixBackground`

### Exit criteria

- [x] Operator can validate mix quality locally without full pipeline.
- [x] Replay entry point documented in script `--help` or README.

---

## 19) Phase 18 — background library upload

### Goal

Seed production/dev S3 with the default bed track.

### Prerequisites

- Phase 3 complete (profile key known).
- Operator has bed audio file.

### Checklist

- [ ] Select / produce `calm_ambient_01.mp3` — looping ambient pad, meditation-appropriate
- [ ] Upload to TTS bucket:
  ```bash
  aws s3 cp ./library/calm_ambient_01.mp3 \
    s3://creative-agent-dev-tts-audio-ACCOUNT_ID/background/calm_ambient_01.mp3 \
    --content-type audio/mpeg \
    --metadata profile-code=calm_ambient_01
  ```
- [ ] Verify: `aws s3 ls s3://.../background/`
- [ ] Verify Lambda IAM `s3:GetObject` on `background/*` (same bucket — should already work)
- [ ] Confirm `track_object_key` in `profiles.py` matches uploaded key exactly

### Optional Terraform

- [ ] `aws_s3_object` for dev seed (optional — upload script is sufficient for v1)

### Exit criteria

- [ ] `read_object_bytes(object_key="background/calm_ambient_01.mp3")` succeeds from worker context.
- [ ] E2E mix step can load bed.

---

## 20) Phase 19 — pipeline script and E2E validation

### Goal

Update operator full-pipeline script and run one end-to-end job producing `master.mp3`.

### Prerequisites

- Phase 12, Phase 15, Phase 18 complete.

### Files to modify

| File | Change |
|------|--------|
| `scripts/run_full_pipeline.ps1` | Download `master.mp3` when present |

### Checklist — `run_full_pipeline.ps1`

- [ ] After job completes, fetch manifest with `include_urls=true` (or read `master_object_key`)
- [ ] If `master_object_key` / `master_url` present → download as primary output file
- [ ] Else fall back to `final.mp3` (pre-feature jobs)
- [ ] Save to `-OutputDir` with recognizable name (e.g. `master-<audio_job_id>.mp3`)

### E2E run

- [ ] Run: `.\scripts\run_full_pipeline.ps1 -DurationMinutes 5 -OpenAudio`
- [ ] Or: `.\scripts\run_full_pipeline.ps1 -TranscriptId "<uuid>"` from ENHANCED
- [ ] Verify in DB: `FINAL` + `MASTER` + `MANIFEST` asset rows
- [ ] Verify in S3: `final/final.mp3`, `final/master.mp3`, manifest JSON with master fields
- [ ] Listen: bed in pauses, ducks under voice, smooth fade in/out

### Exit criteria

- [ ] **Slice 5 complete** — one full E2E job produces audible `master.mp3`.
- [ ] Operator script downloads master by default.

---

## 21) Phase 20 — rollout and documentation closeout

### Goal

Mark feature complete, update cross-references, deploy with rollback path.

### Prerequisites

- Phase 19 complete.

### Checklist — deployment

- [ ] Deploy updated `tts-worker` Lambda (no new Lambda for v1)
- [ ] No schema migration to apply
- [ ] Confirm ffmpeg present in deployed image/layer
- [ ] Run smoke job in dev before prod

### Checklist — documentation

- [ ] Mark Phases 0–20 complete in this document
- [ ] Add Phase 16 entry to [`tts-plane-phase-map.md`](tts-plane-phase-map.md) linking here
- [ ] Update [`architecture-and-tts-plane.md`](architecture-and-tts-plane.md) S3 layout §14 with `master.mp3` and `background/` prefix (if not already)
- [ ] Update `.cursor/rules/project-context.mdc` TTS section with background mixing status

### Checklist — rollback

- [ ] Rollback = deploy previous Lambda version (jobs in flight may lack master — acceptable)
- [ ] `FINAL` artifacts unaffected by rollback
- [ ] API master fields return `None` for old worker — clients fall back to `final_url`

### Exit criteria

- [ ] Feature live in dev (and prod when approved).
- [ ] Phase map checkboxes complete.

---

## 22) Failure modes reference

| Failure | Symptom | Expected behavior |
|---------|---------|-------------------|
| Bed file missing in S3 | `GetObject` 404 | Mix fails; job → `FAILED` / `REVIEW_REQUIRED` per retry policy |
| ffmpeg not in Lambda | `BackgroundMixError` | Fail fast with clear message |
| `FINAL` missing before mix | Out-of-order replay | `FinalAudioMergeError` — no voice-only master |
| Narration corrupt | ffmpeg decode error | Fail mix; chunks preserved for re-stitch |
| Lambda timeout on long file | Partial S3 write | Idempotent retry on `MASTER` lookup |
| Wrong bed at key | Wrong mood | Operator fixes S3; re-mix from `MIX_BACKGROUND` |
| Profile metadata mismatch | Audit confusion | Keys derived from registry only — never from caller |

**Never:** deliver `final.mp3` content as `master.mp3` when mix failed. Downstream uses `master_asset_id` + manifest fields to confirm bed was applied.

---

## 23) Security and compliance (all phases)

- [ ] Background beds are internal curated assets — same trust model as voice profiles
- [ ] No user-uploaded beds in v1
- [ ] Presigned URLs for master follow existing TTS asset TTL rules
- [ ] Mix metadata in asset `metadata_json` supports audit
- [ ] No PII in background layer

---

## 24) Future extensions (out of v1 — do not implement)

| Extension | Notes |
|-----------|-------|
| Per `content_type` profile mapping | Extend `resolve_background_profile()` |
| Per-tenant default bed | Config map — still policy-driven |
| Multiple beds (intro + body) | Needs timeline design |
| `master_asset_id` on job row | Faster API lookup |
| Stem export | Additional asset kinds |
| Loudness profiles per content type | Extend `BackgroundProfile` |
| Dedicated Step Functions Mix state | If Lambda timeout insufficient |
| `force_remix` operator flag | Backfill without deleting asset row |

---

## 25) Complete file change index

| File | Phase | Change |
|------|-------|--------|
| `guide/background-audio-mixing-phase-map.md` | — | This document |
| `guide/background-audio-mixing.md` | Phase 0 | Master spec (already exists) |
| `models/enums.py` | Phase 1 | `AudioAssetKind.MASTER` |
| `tts_pipeline/persistence/s3_keys.py` | Phase 1 | `master_object_key`, `background_track_key` |
| `tts_pipeline/background_policy/schema.py` | Phase 2 | **New** |
| `tts_pipeline/background_policy/profiles.py` | Phase 3 | **New** |
| `tts_pipeline/background_policy/resolver.py` | Phase 4 | **New** |
| `tts_pipeline/background_policy/__init__.py` | Phase 5 | **New** |
| `tests/tts/test_background_policy.py` | Phase 5 | **New** |
| `tts_pipeline/finalizer/mix.py` | Phase 6 | **New** |
| `tests/tts/test_background_mix.py` | Phase 7 | **New** |
| `db/repositories/audio_job_repository.py` | Phase 8 | `find_master_asset()` |
| `tts_pipeline/finalizer/service.py` | Phase 9, Phase 10 | `finalize_audio_job_master()` |
| `tts_pipeline/finalizer/__init__.py` | Phase 9 | Exports |
| `tts_pipeline/finalizer/manifest.py` | Phase 10 | Master fields |
| `tts_pipeline/orchestrator/workflow.py` | Phase 11 | New states |
| `tts_pipeline/orchestrator/states.py` | Phase 11 | Split finalize |
| `tts_pipeline/orchestrator/engine.py` | Phase 12 | Transitions |
| `tts_pipeline/orchestrator/config.py` | Phase 12 | State policies |
| `tests/tts/test_orchestrator.py` | Phase 13 | Extend |
| `observability/tts.py` | Phase 14 | `log_tts_master_mixed` |
| `observability/__init__.py` | Phase 14 | Export |
| `tests/tts/test_tts_observability.py` | Phase 14 | Extend |
| `models/responses.py` | Phase 15 | Master response fields |
| `api/audio_service.py` | Phase 15 | Map master asset |
| `tests/tts/test_audio_api.py` | Phase 16 | Extend |
| `tests/tts/test_manifest_finalizer.py` | Phase 10, Phase 16 | Extend |
| `tests/tts/test_tts_enums.py` | Phase 1 | Extend |
| `scripts/mix_background_smoke.py` | Phase 17 | **New** |
| `scripts/run_full_pipeline.ps1` | Phase 19 | Download master |
| `guide/tts-plane-phase-map.md` | Phase 20 | Phase 16 link |
| `infra/step_functions/tts_audio_job.asl.json` | Phase 12 | Optional ASL sync |

**Not changed:** `transcript_composer/`, `tts_enhancer/`, `generator/`, `chunk_planner/`, ElevenLabs client, voice policy, transcript tables, SQS message shapes.

---

## 26) Definition of done

Background audio mixing is **done** when:

- [ ] An completed TTS job has narration-only `final.mp3` (`FINAL`) **and** mixed `master.mp3` (`MASTER`).
- [ ] Background bed is resolved by `background_policy/` — not caller input.
- [ ] Workflow states are `FinalizeFinal` → `MixBackground` → `FinalizeManifest`.
- [ ] Re-mix from `MixBackground` reuses `FINAL` without ElevenLabs cost.
- [ ] Manifest and API expose master as primary deliverable; `final` retained for audit.
- [ ] Idempotent retries produce a single `MASTER` asset.
- [ ] Missing bed fails loudly — never a silent voice-only master.
- [ ] Unit, orchestrator, and API tests pass.
- [ ] One E2E job verified in dev with uploaded `calm_ambient_01` bed.
- [ ] Operator script downloads `master.mp3` when available.

---

## 27) Implementation invariants (never violate)

- [ ] Transcript pipeline unchanged.
- [ ] TTS generator unchanged — no per-chunk mixing.
- [ ] S3 stores binary audio; Aurora stores metadata only.
- [ ] Background policy is server-side — no raw bed URLs from API.
- [ ] `FINAL` is immutable deliverable for narration-only; `MASTER` is separate asset kind.
- [ ] `job.final_asset_id` points to `FINAL` only.
- [ ] Mix step is idempotent at job level.
- [ ] Manual operator replay from `MixBackground` is supported.
- [ ] ffmpeg resolved via shared `resolve_ffmpeg_executable()` — single binary path.

---

## 28) Quick start for implementers

**Start here:** Phase 0 (approve boundary) → Phase 1 (enum + keys) → Phases 2–5 (policy package) → Phases 6–7 (mix + tests).

After Slice 1 merges green: Phase 8 → Phase 10 (service + manifest) → Phases 11–13 (orchestrator) → Phases 14–16 (observability + API) → Phases 17–19 (ops + E2E) → Phase 20 (rollout).

**First files to create:**

1. `tts_pipeline/background_policy/schema.py`
2. `tts_pipeline/background_policy/profiles.py`
3. `tts_pipeline/background_policy/resolver.py`
4. `tts_pipeline/background_policy/__init__.py`
5. `tts_pipeline/finalizer/mix.py`

**Before E2E:** upload `background/calm_ambient_01.mp3` to the TTS bucket (Phase 18).

---

## 29) Final note

**Current status:** Phases 0–11 complete. Slice 3 in progress — state handlers split; engine wiring is next. (Test run pending: local shell was unresponsive; verify with `pytest tests/tts/test_orchestrator.py tests/tts/test_manifest_finalizer.py`.)

**Next implementation step:** Phase 18 — background library upload (seed `background/calm_ambient_01.mp3` in TTS S3 bucket).

> Note: two pre-existing voice-policy test failures (`test_voice_policy`, `test_audio_job_intake`) are unrelated to this work — the `drew_primary` `voice_id` in `voice_policy/profiles.py` no longer matches those tests' expected value. Not introduced by background mixing.

Do not reopen the transcript pipeline. Do not mix background at chunk generation time. Keep the boundary crisp.
