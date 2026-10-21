# Phase 0 — Foundation and Alignment

> Status: **complete** (repository skeleton + decisions recorded)  
> Spec: [`transcript-enhancement-phase-map.md`](transcript-enhancement-phase-map.md) · [`AGENTS.md`](AGENTS.md) · [`DetailedBreakdown.md`](DetailedBreakdown.md)

## Confirmed architecture (checklist)

| Item | Decision |
|------|----------|
| Subsystem boundary | Ends at **enhanced transcript** — not audio or video |
| Agent split | **Pattern Transcript Composer** (Agent 1) + **ElevenLabs Script Doctor** (Agent 2) — final |
| System of record | **Aurora PostgreSQL** |
| Async handoff | **Amazon SQS** (+ DLQ) — not DB polling |
| Transcript storage | **Immutable versions** — never overwrite in place |
| Agent 2 output modes (priority) | `plain_paste` first → `api_chunked` second → `v3_tagged` later |

## Technology decisions

| Area | Choice | Rationale |
|------|--------|-----------|
| Language | **Python 3.12** | Strong Lambda support, FastAPI ecosystem, team-friendly for LLM/prompt work |
| API framework | **FastAPI** | Typed request/response models, OpenAPI, fits API Gateway + Lambda adapter |
| Lambda packaging | **container or zip** per function under `infra/` | Agents deploy independently |
| DB driver | **asyncpg** (or **psycopg3**) | Aurora PostgreSQL, async-friendly for Lambda |
| Migrations | **Alembic** | Versioned schema in `db/migrations/` |
| Validation | **Pydantic v2** | Shared DTOs in `models/` |
| IaC | **AWS CDK (Python)** or **Terraform** in `infra/` | Team preference at Phase 3; directory reserved now |

## Repository modules

```
api/                  # Intake API (FastAPI) — create job, status, versions
transcript_composer/  # Agent 1 — Pattern Transcript Composer Lambda
tts_enhancer/         # Agent 2 — ElevenLabs Script Doctor Lambda
db/                   # Repositories, transactions, migrations
queues/               # SQS message contracts, publish/consume helpers
models/               # Shared DTOs, enums, domain types
observability/        # Structured logging, metrics, trace correlation
infra/                # AWS resources (Aurora, SQS, Lambda, IAM, alarms)
```

## Environment strategy

| Environment | Purpose | Notes |
|-------------|---------|-------|
| `dev` | Local + personal AWS sandbox | Local Postgres optional; `.env` for secrets |
| `staging` | Full E2E before production | Mirrors prod topology at smaller scale |
| `production` | In-house production traffic | Reserved concurrency on Agent 2; DLQ alarms |

Deploy artifacts and config are **environment-scoped**. Staging must not publish to production queues.

## Environment variable naming

Prefix: **`CREATIVE_AGENT_`** for application config.

| Variable | Example | Used by |
|----------|---------|---------|
| `CREATIVE_AGENT_ENV` | `dev` \| `staging` \| `production` | All |
| `CREATIVE_AGENT_LOG_LEVEL` | `INFO` | All |
| `CREATIVE_AGENT_DATABASE_URL` | `postgresql://...` | API, both Lambdas |
| `CREATIVE_AGENT_DB_SECRET_ARN` | Secrets Manager ARN | Lambdas (preferred in AWS) |
| `CREATIVE_AGENT_ENHANCEMENT_QUEUE_URL` | SQS URL | Agent 1 publish, infra |
| `CREATIVE_AGENT_AWS_REGION` | `us-east-1` | All AWS clients |

Lambda-specific (optional suffix):

- `CREATIVE_AGENT_COMPOSER_*` — Agent 1 only
- `CREATIVE_AGENT_ENHANCER_*` — Agent 2 only

Secrets (API keys, DB passwords) live in **AWS Secrets Manager** in deployed environments — not in repo.

## Logging and trace correlation

- **Format:** one JSON object per log line (structured logging).
- **Required fields:** `timestamp`, `level`, `message`, `service`, `environment`, `correlation_id`.
- **Context fields (when available):** `transcript_id`, `version_id`, `tenant_id`, `sqs_message_id`, `status`.
- **Correlation:** propagate `correlation_id` from API request → Lambda 1 → SQS message attribute or payload trace field → Lambda 2.
- **Content policy:** log transcript IDs and metadata; avoid logging full `content_text` in production unless debug flag enabled.

## Tenant and auth assumptions

- **Audience:** internal in-house tools only (not public internet).
- **Tenant model:** every transcript row carries `tenant_id`; API validates caller may act on that tenant.
- **Auth (v1):** API Gateway with IAM or internal API key header (`X-API-Key`) + `X-Tenant-Id`; refine at Phase 10.
- **Authorization:** least-privilege IAM per Lambda; DB role scoped to required tables only.

## Exit criteria

- [x] Core architecture and build order approved (see phase map recommended path).
- [x] Repository skeleton created.
- [x] No unresolved architectural ambiguity before schema work (Phase 1).

**Next phase:** [Phase 1 — Data model and schema](transcript-enhancement-phase-map.md#phase-1--data-model-and-schema)
