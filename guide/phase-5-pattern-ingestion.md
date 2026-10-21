# Phase 5 — Pattern Knowledge Ingestion

> Status: **complete** (markdown corpus)  
> Data: [`transcript_composer/data/`](../transcript_composer/data/)

## Where to put the corpus files

Place the authoritative markdown exports here (exact filenames):

| File | Path |
|------|------|
| Pattern index | `transcript_composer/data/meditation_patterns_index.md` |
| Examples | `transcript_composer/data/meditation_patterns_examples.md` |

The loader reads `.md` first. JSON with the same base name is also supported if you prefer a pre-converted export later.

Downloaded copies with browser suffixes (e.g. `meditation_patterns_index (1).md`) are accepted as a fallback, but rename to the canonical names above when you can.

## Components

| Component | Path |
|-----------|------|
| Pattern index source | `transcript_composer/data/meditation_patterns_index.md` |
| Examples source | `transcript_composer/data/meditation_patterns_examples.md` |
| Markdown parser | `transcript_composer/knowledge/md_parser.py` |
| Loader | `transcript_composer/knowledge/loader.py` |
| Pattern selector | `transcript_composer/knowledge/pattern_selector.py` |
| Example retriever | `transcript_composer/knowledge/example_retriever.py` |

## Taxonomy codes in API requests

The markdown corpus uses display labels (`GZ-01`, `Millennial`, `P01`). The pipeline normalizes these to API slugs:

| Markdown | API slug |
|----------|----------|
| GZ-01 | `gz_01` |
| ML-02 | `ml_02` |
| Gen Z | `gen_z` |
| P01 | `p01` |

## Usage (Agent 1)

```python
from transcript_composer import PatternSelector, ExampleRetriever, PatternSelectionContext

context = PatternSelectionContext(
    generation_code="millennial",
    wound_id="ml_02",
    stage_no=2,
    pillar_code="p04",
)

selector = PatternSelector()
plan = selector.build_pattern_plan(context)

retriever = ExampleRetriever()
tone_refs = retriever.examples_for_plan(context, plan)
```

## Tests

```powershell
python -m pytest tests/test_pattern_knowledge.py -v
```

**Next phase:** [Phase 6 — Agent 1 implementation](transcript-enhancement-phase-map.md#phase-6--agent-1-implementation)
