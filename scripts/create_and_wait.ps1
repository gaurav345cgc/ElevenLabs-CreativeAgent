# Compose (Agent 1) via Lambda, then wait for Agent 2 enhancement via API.
# Usage: .\scripts\create_and_wait.ps1

param(
    [string]$TenantId = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    [int]$DurationMinutes = 5,
    [string]$ApiKey = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$build = Join-Path $root "infra\terraform\build"
$base = "https://vwhmjhoym3.execute-api.us-east-1.amazonaws.com"

if (-not $ApiKey) { $ApiKey = $env:CREATIVE_AGENT_API_KEY }
if (-not $ApiKey) {
    $envFile = Join-Path $root ".env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^\s*CREATIVE_AGENT_API_KEY\s*=\s*(.+)\s*$') {
                $ApiKey = $Matches[1].Trim().Trim('"').Trim("'")
            }
        }
    }
}
if (-not $ApiKey) {
    $keyFile = Join-Path $build "deployed_api_key.txt"
    if (Test-Path $keyFile) {
        $ApiKey = (Get-Content $keyFile -Raw).Trim()
    }
}
if (-not $ApiKey) {
    Write-Error "Missing API key. Set CREATIVE_AGENT_API_KEY in .env, pass -ApiKey, or update infra/terraform/build/deployed_api_key.txt"
}

$headers = @{
    "X-API-Key"   = $ApiKey
    "X-Tenant-Id" = $TenantId
}

$payload = @{
    tenant_id = $TenantId
    content_type = "guided_meditation"
    generation_code = "millennial"
    wound_id = "ml_02"
    stage_no = 2
    target_duration_minutes = $DurationMinutes
    pillar_code = "p04"
} | ConvertTo-Json -Compress

$payloadPath = Join-Path $env:TEMP "composer-payload.json"
$outPath = Join-Path $env:TEMP "composer-out.json"
[System.IO.File]::WriteAllText($payloadPath, $payload)

Write-Host "Running Agent 1 (composer)..." -ForegroundColor Cyan
aws lambda invoke --function-name creative-agent-dev-composer `
    --cli-binary-format raw-in-base64-out --cli-read-timeout 600 `
    --payload "fileb://$payloadPath" $outPath | Out-Null

$invoke = Get-Content $outPath | ConvertFrom-Json
if ($invoke.statusCode -ne 201) {
    Write-Error "Composer failed: $($invoke.body)"
}

$created = $invoke.body | ConvertFrom-Json
$tid = $created.transcript_id
Write-Host "Transcript $tid queued for enhancement (Agent 2 runs automatically via SQS)." -ForegroundColor Green

Write-Host "Waiting for ENHANCED..." -ForegroundColor Cyan
$deadline = (Get-Date).AddMinutes(5)
do {
    $status = Invoke-RestMethod -Uri "$base/transcripts/$tid" -Headers $headers

    if ($status.status -eq "ENHANCED") {
        $versions = Invoke-RestMethod -Uri "$base/transcripts/$tid/versions?include_content=true" -Headers $headers
        $enhanced = ($versions.versions | Where-Object { $_.version_kind -eq "ELEVENLABS_ENHANCED" }).content_text
        Write-Host "`n=== ENHANCED ===" -ForegroundColor Green
        Write-Host $enhanced
        return @{
            transcript_id = $tid
            status        = $status.status
            enhanced_content_text = $enhanced
            versions      = $versions.versions
        }
    }

    if ($status.status -in @("FAILED_ENHANCEMENT", "REVIEW_REQUIRED")) {
        Write-Error "Enhancement failed: status=$($status.status) error=$($status.last_error)"
    }

    Write-Host "  still $($status.status)..."
    Start-Sleep -Seconds 10
} while ((Get-Date) -lt $deadline)

Write-Error "Timed out waiting for enhancement. Poll: GET $base/transcripts/$tid"