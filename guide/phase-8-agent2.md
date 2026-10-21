# Phase 8 — Agent 2 Implementation

> Status: **complete**  
> Handler: [`tts_enhancer/handler.py`](../tts_enhancer/handler.py)

## Objective

Implement the ElevenLabs Script Doctor — rewrite raw transcripts into speakable, ElevenLabs-ready narration packages.

## Components

| Component | Path |
|-----------|------|
| Rewrite pipeline | `tts_enhancer/rewrite/` |
| Enhancement engine | `tts_enhancer/engine.py` |
| Transaction service | `tts_enhancer/enhancement_service.py` |
| DB persist | `tts_enhancer/persistence.py` |
| SQS processor | `tts_enhancer/processor.py` |
| Lambda handler | `tts_enhancer/handler.py` |

## Rewrite pipeline (deterministic)

1. **Structural cleanup** — fillers, artifacts, duplicate starts, sentence fragments
2. **Token normalization** — numbers and acronyms to spoken form + pronunciation notes
3. **Punctuation control** — spacing, ellipses, em-dashes
4. **Beat grouping** — short speakable beats
5. **Chunking** — `api_chunked` mode adds `previous_text` / `next_text` continuity
6. **Voice direction notes** — delivery hints from script register

## Transaction flow

1. Skip if enhanced version already exists (idempotent)
2. Atomic `PENDING_ENHANCEMENT` → `ENHANCING` claim
3. Load `RAW_PATTERN` version from Aurora
4. Run enhancement engine
5. Insert `ELEVENLABS_ENHANCED` version
6. Set `current_version_id` + status `ENHANCED`
7. On quality failure → `REVIEW_REQUIRED`

## Output modes

| Mode | Status |
|------|--------|
| `plain_paste` | Implemented — beats, `plain_paste_text`, voice notes separate |
| `api_chunked` | Implemented — chunks with continuity fields |
| `v3_tagged` | Implemented — sparse tags with fallback |

## Tests

```powershell
python -m pytest tests/test_enhancer_rewrite.py tests/test_agent2_service.py -v
```

Full pipeline (Agent 1 → Agent 2):

```powershell
python -m pytest tests/test_agent2_service.py tests/test_queue_handoff.py -v
```

## Lambda entrypoint

```
tts_enhancer.handler.handler
```

Enable SQS trigger after deploying Lambda:

```hcl
enhancer_lambda_function_name = "creative-agent-dev-enhancer"
enhancer_sqs_trigger_enabled  = true
```

**Next phase:** [Phase 9 — ElevenLabs formatting modes](phase-9-formatting-modes.md) → [Phase 10 — API](transcript-enhancement-phase-map.md#phase-10--api-and-internal-control-plane)
