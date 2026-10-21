# Phase 9 — ElevenLabs Formatting Modes

> Status: **complete**  
> Formatters: `tts_enhancer/formats/`

## Objective

Expand Agent 2 outputs into clearly defined consumer-ready modes.

## Modes

| Mode | `content_json` artifacts | `content_text` |
|------|--------------------------|----------------|
| `plain_paste` | `plain_paste_text`, `beats`, `voice_notes_text` | Full narration (no voice notes) |
| `api_chunked` | `chunks[]` with sequence, continuity, duration | Full narration |
| `v3_tagged` | `api_chunked` + sparse inline tags, `extra.tagging_applied` | Full narration |

Voice direction and pronunciation notes live in **`voice_notes_text`** and **`metadata_json`** — never mixed into paste/API narration text.

## Components

| Formatter | Path |
|-----------|------|
| Plain paste layout | `tts_enhancer/formats/plain_paste.py` |
| API chunk edges | `tts_enhancer/formats/api_chunked.py` |
| v3 sparse tags | `tts_enhancer/formats/v3_tagged.py` |
| Mode orchestration | `tts_enhancer/formats/__init__.py` |

## `plain_paste`

- Section headers (`## Opening`, etc.) when sectioned script exists
- Beats separated by blank lines
- Voice notes in `voice_notes_text` only

## `api_chunked`

- Chunk array with `sequence`, `previous_text`, `next_text`
- `estimated_duration_seconds` per chunk
- Continuity-safe punctuation at chunk edges (no trailing commas; complete sentences)

## `v3_tagged`

- Same chunk structure as `api_chunked`
- Max 2 tags per chunk; rejects stacked tag runs
- Falls back to untagged chunks when quality check fails (`extra.tagging_applied = false`)

## Tests

```powershell
python -m pytest tests/test_formatting_modes.py tests/test_enhancer_rewrite.py -v
```

**Next phase:** [Phase 10 — API](phase-10-api.md) → [Phase 11 — Observability](transcript-enhancement-phase-map.md#phase-11--observability-and-operations)
