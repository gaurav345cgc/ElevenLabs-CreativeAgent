# Phase 6 — Agent 1 Implementation

> Status: **complete** — OpenAI narration when API key is configured; template fallback for offline/tests  
> Handler: [`transcript_composer/handler.py`](../transcript_composer/handler.py)

## Script generation modes

| `CREATIVE_AGENT_SCRIPT_GENERATOR` | Behavior |
|-----------------------------------|----------|
| `auto` (default) | OpenAI if key found, else template |
| `openai` | Require OpenAI key |
| `template` | Offline deterministic scaffold |

API key resolution order:

1. `CREATIVE_AGENT_OPENAI_API_KEY`
2. `OPENAI_API_KEY`
3. `CREATIVE_AGENT_MODEL_PROVIDER_SECRET_ARN` → Secrets Manager JSON `api_key`

## Components

| Component | Path |
|-----------|------|
| Lambda handler | `transcript_composer/handler.py` |
| Orchestrator | `transcript_composer/service.py` |
| Composition | `transcript_composer/composition_service.py` |
| Script generation | `transcript_composer/script_generator.py` |
| Title / duration | `transcript_composer/title.py`, `duration.py` |
| DB persist | `transcript_composer/persistence.py` |
| SQS publish | `queues/publisher.py` |

## Flow

1. Validate `CreateTranscriptRequest`
2. Select pattern plan + example tone references (Phase 5)
3. Generate sectioned script (template generator)
4. Transaction: insert transcript → `RAW_PATTERN` version → `PENDING_ENHANCEMENT`
5. Publish `EnhancementJobMessage` to SQS (after commit)

## Local test

```powershell
python -m pytest tests/test_composition_service.py tests/test_agent1_service.py -v
```

## Manual invoke (Python)

```python
from uuid import uuid4
from models.requests import CreateTranscriptRequest
from transcript_composer import Agent1Service, build_agent1_service_for_tests

request = CreateTranscriptRequest(
    tenant_id=uuid4(),
    content_type="guided_meditation",
    generation_code="millennial",
    wound_id="ml_02",
    stage_no=2,
    target_duration_minutes=10,
    pillar_code="p04",
)

service, publisher = build_agent1_service_for_tests()
result = service.run(request)
print(result.output.title, publisher.messages[0].idempotency_key)
```

## Lambda entrypoint

```
transcript_composer.handler.handler
```

**Next phase:** [Phase 7 — Queue contract](transcript-enhancement-phase-map.md#phase-7--queue-contract-and-asynchronous-handoff)
