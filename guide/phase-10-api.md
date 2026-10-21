# Phase 10 — API and Internal Control Plane

> Status: **complete**  
> App: [`api/main.py`](../api/main.py)

## Objective

Expose the subsystem through internal APIs for creating jobs, fetching status, and retrieving transcript versions.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/transcripts` | Create transcript job (Agent 1 + SQS) |
| `GET` | `/transcripts/{id}` | Transcript status and metadata |
| `GET` | `/transcripts/{id}/versions` | Version history (`?include_content=true` optional) |
| `POST` | `/transcripts/{id}/retry-enhancement` | Re-queue failed/review transcripts |
| `GET` | `/health` | Liveness probe |

## Auth (internal v1)

| Header | Required | Purpose |
|--------|----------|---------|
| `X-API-Key` | When `CREATIVE_AGENT_API_KEY` is set | Internal API key |
| `X-Tenant-Id` | GET + retry | Tenant scoping |
| `X-Correlation-Id` | Optional | Trace propagation |

When `CREATIVE_AGENT_API_KEY` is empty, key checks are skipped for local dev.

## Local run

```powershell
pip install -e ".[dev]"
uvicorn api.main:app --reload --port 8080
```

```powershell
curl -X POST http://localhost:8080/transcripts `
  -H "Content-Type: application/json" `
  -H "X-Tenant-Id: <tenant-uuid>" `
  -d '{"tenant_id":"<tenant-uuid>","content_type":"guided_meditation","generation_code":"millennial","wound_id":"ml_02","stage_no":2,"target_duration_minutes":10,"pillar_code":"p04"}'
```

## Lambda entrypoint

```
api.handler.handler
```

(Mangum adapter for API Gateway.)

## Tests

```powershell
python -m pytest tests/test_api.py -v
```

**Next phase:** [Phase 11 — Observability and operations](transcript-enhancement-phase-map.md#phase-11--observability-and-operations)
