# Creative Agent — AWS infrastructure

Terraform provisions Phase 3+ resources **except** the Aurora cluster you already created manually.

## What Terraform creates (per environment)

| Resource | Name pattern |
|----------|----------------|
| SQS enhancement queue | `creative-agent-{env}-enhancement` |
| SQS DLQ | `creative-agent-{env}-enhancement-dlq` |
| Lambda Agent 1 | `creative-agent-{env}-composer` |
| Lambda Agent 2 | `creative-agent-{env}-enhancer` |
| Lambda Intake API | `creative-agent-{env}-api` |
| Lambda TTS worker | `creative-agent-{env}-tts-worker` |
| SQS TTS queue | `creative-agent-{env}-tts-audio` |
| API Function URL | output `api_function_url` |
| IAM roles | `creative-agent-{env}-*-lambda` |
| Secrets Manager DB | `creative-agent-{env}/database` |
| Secrets Manager models | `creative-agent-{env}/model-provider` |
| CloudWatch log groups | `/aws/lambda/creative-agent-{env}-*` |
| CloudWatch alarms | queue depth, queue age, DLQ, Lambda errors |
| SNS topic | `creative-agent-{env}-alarms` |
| S3 TTS audio bucket | `creative-agent-{env}-tts-audio-{account_id}` |
| IAM TTS pipeline role | `creative-agent-{env}-tts-pipeline-lambda` |

## Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.5
- AWS CLI configured (`aws sts get-caller-identity`)
- Python 3.12 + project venv
- Aurora dev cluster running with schema migrated (`alembic upgrade head`)
- Aurora security group allows inbound PostgreSQL (5432) from Lambda (public subnet / no VPC on Lambdas for dev)

## Deploy dev (queues + Lambdas)

```powershell
# 1. Build Linux-compatible Lambda zips (one per function)
cd "d:\GenMyo Main\Creative Agent"
.\.venv\Scripts\python.exe scripts\build_lambda_package.py

# 2. Terraform
cd infra\terraform
copy environments\dev.tfvars.example environments\dev.tfvars
# Edit db_host, db_secret_username if needed

terraform init
terraform plan `
  -var-file=environments/dev.tfvars `
  -var="db_secret_password=YOUR_DB_PASSWORD" `
  -var="model_provider_api_key=YOUR_OPENAI_KEY" `
  -var="api_key=YOUR_API_KEY" `
  -var="elevenlabs_api_key=YOUR_ELEVENLABS_KEY"

terraform apply `
  -var-file=environments/dev.tfvars `
  -var="db_secret_password=YOUR_DB_PASSWORD" `
  -var="model_provider_api_key=YOUR_OPENAI_KEY" `
  -var="api_key=YOUR_API_KEY" `
  -var="elevenlabs_api_key=YOUR_ELEVENLABS_KEY"
```

After apply, note outputs:

- `api_gateway_url` — primary base URL for the intake API (30s timeout on requests)
- `api_function_url` — optional Lambda URL (if your account allows public Function URLs)
- `enhancement_queue_url` — SQS queue (also set in Lambda env)

## Smoke test (deployed API)

```powershell
# Full end-to-end: compose -> enhance -> TTS on Lambda -> download final.mp3
cd "d:\GenMyo Main\Creative Agent"
.\scripts\run_full_pipeline.ps1 -OpenAudio

# Or step-by-step transcript only (enhancement wait):
.\scripts\create_and_wait.ps1
```

Manual API smoke (transcript intake only):

```powershell
$base = "<api_gateway_url output>"
$tenant = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
$headers = @{
  "X-API-Key"   = "YOUR_API_KEY"
  "X-Tenant-Id" = $tenant
  "Content-Type" = "application/json"
}

# Health
Invoke-RestMethod -Uri "$base/health"

# Create transcript (Agent 1 + SQS publish; Agent 2 runs automatically)
$body = @{
  tenant_id = $tenant
  title = "Lambda deploy smoke test"
  brief = @{
    theme = "calm"
    duration_minutes = 5
    voice_style = "warm"
    enhancement_mode = "plain_paste"
  }
} | ConvertTo-Json -Depth 5

$result = Invoke-RestMethod -Uri "$base/transcripts" -Method POST -Headers $headers -Body $body
$result

# Poll status until ENHANCED
Invoke-RestMethod -Uri "$base/transcripts/$($result.transcript_id)" -Headers $headers
```

Agent 2 is triggered by SQS (`enhancer_sqs_trigger_enabled = true`). Enhancement can take several minutes.

## Smoke test (TTS on Lambda)

TTS runs asynchronously on `creative-agent-{env}-tts-worker` (SQS trigger), not locally.

```powershell
$base = "<api_gateway_url output>"
$tenant = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
$headers = @{
  "X-API-Key"   = "YOUR_API_KEY"
  "X-Tenant-Id" = $tenant
  "Content-Type" = "application/json"
}

# Resolve latest ELEVENLABS_ENHANCED version for an ENHANCED transcript
$transcriptId = "<transcript_uuid>"
$versions = Invoke-RestMethod -Uri "$base/transcripts/$transcriptId/versions?include_content=false" -Headers $headers
$versionId = ($versions.versions | Where-Object { $_.version_kind -eq "ELEVENLABS_ENHANCED" } | Select-Object -First 1).version_id

# Create audio job + enqueue workflow (returns immediately)
$body = @{
  tenant_id = $tenant
  transcript_id = $transcriptId
  transcript_version_id = $versionId
  voice_profile_code = "gentle_feminine_primary"
} | ConvertTo-Json

$job = Invoke-RestMethod -Uri "$base/audio-jobs" -Method POST -Headers $headers -Body $body
$job

# Poll until COMPLETED (generation can take several minutes)
Invoke-RestMethod -Uri "$base/audio-jobs/$($job.audio_job_id)" -Headers $headers

# Manifest + presigned URLs
Invoke-RestMethod -Uri "$base/audio-jobs/$($job.audio_job_id)/manifest?include_urls=true" -Headers $headers
```

Worker logs: `/aws/lambda/creative-agent-dev-tts-worker`

## Re-deploy code only

After code changes:

```powershell
.\.venv\Scripts\python.exe scripts\build_lambda_package.py
cd infra\terraform
terraform apply -var-file=environments/dev.tfvars -var="db_secret_password=..." -var="model_provider_api_key=..." -var="api_key=..."
```

Terraform updates all four Lambdas when zip hashes change (composer, enhancer, api, tts-worker).

## After apply — local `.env`

For local uvicorn against AWS resources:

```env
CREATIVE_AGENT_ENHANCEMENT_QUEUE_URL=<enhancement_queue_url output>
CREATIVE_AGENT_TTS_QUEUE_URL=<tts_audio_queue_url output>
CREATIVE_AGENT_TTS_AUDIO_BUCKET=<tts_audio_bucket_name output>
CREATIVE_AGENT_DATABASE_URL=postgresql://...   # or CREATIVE_AGENT_DB_SECRET_ARN
CREATIVE_AGENT_OPENAI_API_KEY=...
CREATIVE_AGENT_ELEVENLABS_API_KEY=...
CREATIVE_AGENT_API_KEY=...
```

## Verify

```powershell
aws lambda get-function --function-name creative-agent-dev-api
aws lambda get-function-url-config --function-name creative-agent-dev-api
aws lambda list-event-source-mappings --function-name creative-agent-dev-enhancer
aws lambda list-event-source-mappings --function-name creative-agent-dev-tts-worker
aws sqs get-queue-url --queue-name creative-agent-dev-tts-audio
aws sqs get-queue-url --queue-name creative-agent-dev-enhancement
```

## RDS Proxy decision (Phase 3)

**Dev:** `enable_rds_proxy = false` — not required for low Lambda concurrency.  
**Production:** set `enable_rds_proxy = true` when deploying Lambdas at scale.

## TTS audio bucket (Phase 3)

Terraform creates `creative-agent-{env}-tts-audio-{account_id}` with:

- SSE-S3 encryption (or SSE-KMS when `tts_audio_kms_key_arn` is set)
- Public access blocked, bucket owner enforced
- TLS-only bucket policy
- Lifecycle: objects tagged `artifact_kind=debug` expire after `tts_debug_object_expiration_days` (default 90)
- IAM role `creative-agent-{env}-tts-pipeline-lambda` — least-privilege read/write on that bucket only

Object key layout is implemented in `tts_pipeline/persistence/s3_keys.py`.

After `terraform apply`, set `CREATIVE_AGENT_TTS_AUDIO_BUCKET` from output `tts_audio_bucket_name`.

```powershell
aws s3 ls s3://$(terraform output -raw tts_audio_bucket_name)/
```

## Staging / production

Use separate `environments/staging.tfvars` and `environments/production.tfvars` (from `.example` templates).  
**Never** point staging at production queues or secrets.

## Destroy (dev only)

```powershell
terraform destroy -var-file=environments/dev.tfvars -var="db_secret_password=..."
```

Does **not** delete your Aurora cluster.
