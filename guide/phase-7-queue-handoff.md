# Phase 7 — Queue Contract and Asynchronous Handoff

> Status: **complete**  
> Consumer: [`tts_enhancer/handler.py`](../tts_enhancer/handler.py)

## Objective

Stabilize identifier-only SQS handoff from Agent 1 to Agent 2 with idempotency, partial batch failures, and Terraform trigger wiring.

## Components

| Component | Path |
|-----------|------|
| Message contract | `models/messages.py` |
| SQS publisher | `queues/publisher.py` |
| SQS consumer parser | `queues/consumer.py` |
| Idempotency helpers | `queues/idempotency.py` |
| Processor protocol (Phase 8) | `queues/processor.py` |
| Handoff service | `tts_enhancer/consumer_service.py` |
| Lambda 2 entrypoint | `tts_enhancer/handler.py` |
| SQS → Lambda mapping | `infra/terraform/lambda.tf` |

## Message schema (identifier-only)

```json
{
  "schema_version": "1.0",
  "transcript_id": "uuid",
  "tenant_id": "uuid",
  "raw_version_id": "uuid",
  "requested_output_mode": "plain_paste",
  "voice_model": "eleven_multilingual_v2",
  "idempotency_key": "{transcript_id}:{raw_version_id}:enhancement-v1",
  "correlation_id": "optional-trace-id"
}
```

No transcript text in the queue body. Publisher also sets SQS message attributes `idempotency_key` and `correlation_id`.

## Consumer flow

1. Parse SQS Lambda event → `EnhancementJobMessage`
2. Skip if enhanced version already exists (`should_skip_duplicate_enhancement`)
3. Validate tenant + raw version against Aurora
4. Record `enhancement_handoff_validated` audit event
5. Delegate to `EnhancementJobProcessor` (Phase 8 implements rewrite)
6. Return `batchItemFailures` for per-message retry / DLQ routing

## Retry and DLQ (Terraform)

| Setting | Default | Location |
|---------|---------|----------|
| Visibility timeout | 300s | `sqs_visibility_timeout_seconds` |
| Max receives before DLQ | 3 | `sqs_max_receive_count` |
| Batch size | 1 | `enhancer_lambda_batch_size` |
| Partial batch failures | enabled | `function_response_types` in `lambda.tf` |

Enable SQS trigger after Agent 2 Lambda is deployed:

```hcl
enhancer_lambda_function_name = "creative-agent-dev-enhancer"
enhancer_sqs_trigger_enabled  = true
```

Keep `enhancer_sqs_trigger_enabled = false` until Phase 8 — the default processor raises so messages would retry into the DLQ.

## Tests

```powershell
python -m pytest tests/test_queue_handoff.py -v
```

With Aurora:

```powershell
python -m pytest tests/test_queue_handoff.py tests/test_agent1_service.py -v
```

## Lambda entrypoint

```
tts_enhancer.handler.handler
```

**Next phase:** [Phase 8 — Agent 2 implementation](transcript-enhancement-phase-map.md#phase-8--agent-2-implementation)
