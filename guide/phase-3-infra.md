# Phase 3 — Infrastructure Baseline

> Status: **complete (dev)** — `terraform apply` succeeded, 19 resources  
> Aurora: `creative-agent-dev-v1` · Account: `754639201125` · Region: `us-east-1`

## Terraform outputs (dev)

| Output | Value |
|--------|--------|
| Enhancement queue | `https://sqs.us-east-1.amazonaws.com/754639201125/creative-agent-dev-enhancement` |
| DLQ | `https://sqs.us-east-1.amazonaws.com/754639201125/creative-agent-dev-enhancement-dlq` |
| DB secret ARN | `arn:aws:secretsmanager:us-east-1:754639201125:secret:creative-agent-dev/database-GTuNOP` |
| Model secret ARN | `arn:aws:secretsmanager:us-east-1:754639201125:secret:creative-agent-dev/model-provider-NNmLvM` |
| Composer role | `arn:aws:iam::754639201125:role/creative-agent-dev-composer-lambda` |
| Enhancer role | `arn:aws:iam::754639201125:role/creative-agent-dev-enhancer-lambda` |
| Alarms SNS | `arn:aws:sns:us-east-1:754639201125:creative-agent-dev-alarms` |

## Add to `.env`

```env
CREATIVE_AGENT_ENHANCEMENT_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/754639201125/creative-agent-dev-enhancement
CREATIVE_AGENT_DB_SECRET_ARN=arn:aws:secretsmanager:us-east-1:754639201125:secret:creative-agent-dev/database-GTuNOP
```

Keep your existing `CREATIVE_AGENT_DATABASE_URL` for local Alembic; Lambdas will use Secrets Manager.

## Optional: subscribe to alarms

SNS topic `creative-agent-dev-alarms` — add email subscription in AWS Console to get DLQ/backlog alerts.

## Staging / production

Templates: `infra/terraform/environments/staging.tfvars.example`, `production.tfvars.example`

**Next phase:** [Phase 4 — Persistence layer](transcript-enhancement-phase-map.md#phase-4--persistence-layer)
