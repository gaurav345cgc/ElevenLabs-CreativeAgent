# End-to-end: compose -> enhance -> TTS on Lambda -> download final.mp3
#
# Usage:
#   .\scripts\run_full_pipeline.ps1
#   .\scripts\run_full_pipeline.ps1 -DurationMinutes 5
#   .\scripts\run_full_pipeline.ps1 -TranscriptId "<uuid>"   # skip compose; start from ENHANCED
#
# Requires: AWS CLI, CREATIVE_AGENT_API_KEY in .env (or -ApiKey)

param(
    [string]$TenantId = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    [int]$DurationMinutes = 5,
    [string]$ApiKey = "",
    [string]$ApiBase = "",
    [string]$ComposerFunctionName = "creative-agent-dev-composer",
    [string]$VoiceProfileCode = "drew_primary",
    [string]$TranscriptId = "",
    [string]$OutputDir = "",
    [int]$EnhancementTimeoutMinutes = 15,
    [int]$TtsTimeoutMinutes = 45,
    [int]$PollSeconds = 15,
    [switch]$AcceptPartial,
    [switch]$OpenAudio,
    [switch]$NoAutoRetryMix
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$build = Join-Path $root "infra\terraform\build"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Sanitize-HeaderValue {
    param([string]$Value)
    if ($null -eq $Value) { return "" }
    # Strip CR/LF/BOM and other control chars that break Invoke-RestMethod headers.
    return (($Value -replace '[\u0000-\u001F\u007F]', '') -replace '^\uFEFF', '').Trim().Trim('"').Trim("'")
}

function Resolve-ApiKey {
    param([string]$Override)
    if ($Override) { return (Sanitize-HeaderValue $Override) }
    if ($env:CREATIVE_AGENT_API_KEY) {
        return (Sanitize-HeaderValue $env:CREATIVE_AGENT_API_KEY)
    }

    $envFile = Join-Path $root ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*CREATIVE_AGENT_API_KEY\s*=\s*(.+)\s*$') {
                return (Sanitize-HeaderValue $Matches[1])
            }
        }
    }

    $keyFile = Join-Path $build "deployed_api_key.txt"
    if (Test-Path $keyFile) {
        return (Sanitize-HeaderValue (Get-Content $keyFile -Raw))
    }

    throw "Missing API key. Set CREATIVE_AGENT_API_KEY in .env or pass -ApiKey"
}

function Resolve-TtsAudioBucket {
    if ($env:CREATIVE_AGENT_TTS_AUDIO_BUCKET) {
        return $env:CREATIVE_AGENT_TTS_AUDIO_BUCKET.Trim()
    }
    $envFile = Join-Path $root ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*CREATIVE_AGENT_TTS_AUDIO_BUCKET\s*=\s*(.+)\s*$') {
                return $Matches[1].Trim().Trim('"').Trim("'")
            }
        }
    }
    throw "Missing TTS bucket. Set CREATIVE_AGENT_TTS_AUDIO_BUCKET in .env"
}

function Invoke-Api {
    param(
        [string]$Method = "GET",
        [string]$Path,
        [object]$Body = $null
    )
    $uri = "$script:BaseUrl$Path"
    $params = @{
        Uri     = $uri
        Method  = $Method
        Headers = $script:Headers
    }
    if ($null -ne $Body) {
        $params.Body = ($Body | ConvertTo-Json -Depth 6)
        $params.ContentType = "application/json"
    }
    return Invoke-RestMethod @params
}

function Wait-TranscriptEnhanced {
    param(
        [string]$Id,
        [datetime]$Deadline
    )
    Write-Step "Waiting for transcript enhancement (Agent 2 via SQS)..."
    do {
        $status = Invoke-Api -Path "/transcripts/$Id"
        $label = $status.status
        if ($status.last_error) { $label += " ($($status.last_error))" }
        Write-Host "  transcript status: $label"

        switch ($status.status) {
            "ENHANCED" { return $status }
            { $_ -in @("FAILED_ENHANCEMENT", "REVIEW_REQUIRED") } {
                throw "Enhancement failed: status=$($status.status) error=$($status.last_error)"
            }
        }
        Start-Sleep -Seconds $PollSeconds
    } while ((Get-Date) -lt $Deadline)

    throw "Timed out waiting for ENHANCED. Poll: GET $script:BaseUrl/transcripts/$Id"
}

function Start-Composer {
    param([datetime]$Deadline)
    Write-Step "Running Agent 1 (composer Lambda)..."

    $payload = @{
        tenant_id               = $TenantId
        content_type            = "guided_meditation"
        generation_code         = "millennial"
        wound_id                = "ml_02"
        stage_no                = 2
        target_duration_minutes = $DurationMinutes
        pillar_code             = "p04"
    } | ConvertTo-Json -Compress

    $payloadPath = Join-Path $env:TEMP "composer-payload.json"
    $outPath = Join-Path $env:TEMP "composer-out.json"
    [System.IO.File]::WriteAllText($payloadPath, $payload)

    aws lambda invoke --function-name $ComposerFunctionName `
        --cli-binary-format raw-in-base64-out --cli-read-timeout 600 `
        --payload "fileb://$payloadPath" $outPath | Out-Null

    $invoke = Get-Content $outPath | ConvertFrom-Json
    if ($invoke.statusCode -ne 201) {
        throw "Composer failed: $($invoke.body)"
    }

    $created = $invoke.body | ConvertFrom-Json
    $tid = $created.transcript_id
    Write-Host "  transcript_id: $tid" -ForegroundColor Green
    Write-Host "  queued for enhancement (Agent 2 runs automatically)"

    Wait-TranscriptEnhanced -Id $tid -Deadline $Deadline | Out-Null
    return $tid
}

function Get-EnhancedVersionId {
    param([string]$Id)
    $versions = Invoke-Api -Path "/transcripts/$Id/versions?include_content=false"
    # Prefer human-reviewed APPROVED_FINAL (carries Script Hub pause markers).
    $approved = $versions.versions | Where-Object { $_.version_kind -eq "APPROVED_FINAL" } | Select-Object -Last 1
    if ($approved) {
        return $approved.version_id
    }
    $enhanced = $versions.versions | Where-Object { $_.version_kind -eq "ELEVENLABS_ENHANCED" } | Select-Object -First 1
    if (-not $enhanced) {
        throw "No ELEVENLABS_ENHANCED or APPROVED_FINAL version for transcript $Id"
    }
    return $enhanced.version_id
}

function Start-AudioJob {
    param(
        [string]$Id,
        [string]$VersionId
    )
    Write-Step "Creating audio job and enqueueing TTS worker (Lambda via SQS)..."

    $job = Invoke-Api -Method POST -Path "/audio-jobs" -Body @{
        tenant_id             = $TenantId
        transcript_id         = $Id
        transcript_version_id = $VersionId
        voice_profile_code    = $VoiceProfileCode
    }

    Write-Host "  audio_job_id:    $($job.audio_job_id)" -ForegroundColor Green
    Write-Host "  job status:      $($job.status)"
    Write-Host "  created:         $($job.created)"
    Write-Host "  queue_message:   $($job.queue_message_id)"
    return $job
}

function Wait-AudioJob {
    param(
        [string]$AudioJobId,
        [datetime]$Deadline
    )
    Write-Step "Waiting for TTS worker (chunk synthesis + merge on Lambda)..."
    $lastStatus = $null
    $finalizeHintShown = $false
    do {
        $status = Invoke-Api -Path "/audio-jobs/$AudioJobId"
        $chunks = if ($status.total_chunks) {
            "$($status.completed_chunks)/$($status.total_chunks)"
        } else {
            "$($status.completed_chunks)/?"
        }
        $pauseNote = ""
        if ($null -ne $status.pause_hold_count) {
            $pauseNote = "  pauses=$($status.pause_hold_count)/$($status.pause_total_hold_seconds)s"
        }
        $line = "  audio job: $($status.status)  chunks $chunks  failed=$($status.failed_chunks)$pauseNote"
        if ($line -ne $lastStatus) {
            Write-Host $line
            $lastStatus = $line
        }
        if (
            -not $finalizeHintShown -and
            $status.status -eq "GENERATING" -and
            $status.total_chunks -gt 0 -and
            $status.completed_chunks -eq $status.total_chunks
        ) {
            Write-Host "  (chunks done - worker may be stitching holds, mixing bed, writing manifest; can take several minutes)" -ForegroundColor DarkGray
            $finalizeHintShown = $true
        }

        switch ($status.status) {
            "COMPLETED" { return $status }
            "PARTIALLY_FAILED" {
                if ($status.final_asset_id) {
                    Write-Host "  job finished with PARTIALLY_FAILED but final narration exists." -ForegroundColor Yellow
                    if ($status.last_error) {
                        Write-Host "  last_error: $($status.last_error)" -ForegroundColor Yellow
                    }
                    return $status
                }
                if ($AcceptPartial) {
                    Write-Host "  accepting PARTIALLY_FAILED (AcceptPartial)" -ForegroundColor Yellow
                    return $status
                }
                throw (
                    "TTS PARTIALLY_FAILED with no final asset. last_error=$($status.last_error)"
                )
            }
            "REVIEW_REQUIRED" {
                if ($AcceptPartial -or (Test-AudioJobRecoverable -Status $status)) {
                    if (Test-MixFailureError -Status $status) {
                        Write-Host "  REVIEW_REQUIRED after background mix failure (not ElevenLabs quota)." -ForegroundColor Yellow
                        Write-Host "  Apply terraform tts_lambda_ephemeral_storage_mb=2048, redeploy worker, re-enqueue." -ForegroundColor Yellow
                    }
                    if ($status.last_error) {
                        Write-Host "  last_error: $($status.last_error)" -ForegroundColor Yellow
                    }
                    return $status
                }
                $detail = $status.last_error
                if ($detail -match "quota|credits remain") {
                    throw (
                        "TTS blocked by ElevenLabs quota: {0}/{1} chunks completed. " +
                        "Top up credits at https://elevenlabs.io and re-run with the same audio_job_id " +
                        "(POST /audio-jobs re-enqueues retry) or start a new transcript."
                    ) -f $status.completed_chunks, $status.total_chunks
                }
                throw (
                    "TTS finished with REVIEW_REQUIRED: {0}/{1} chunks, {2} failed. " +
                    "Likely ElevenLabs quota. Top up credits and retry, " +
                    "or pass -AcceptPartial to download partial audio."
                ) -f $status.completed_chunks, $status.total_chunks, $status.failed_chunks
            }
            "FAILED" {
                throw (
                    "TTS job FAILED ({0} chunk failures). Check CloudWatch /aws/lambda/creative-agent-dev-tts-worker"
                ) -f $status.failed_chunks
            }
        }
        Start-Sleep -Seconds $PollSeconds
    } while ((Get-Date) -lt $Deadline)

    $status = Invoke-Api -Path "/audio-jobs/$AudioJobId"
    if ($status.status -in @("COMPLETED", "PARTIALLY_FAILED", "REVIEW_REQUIRED") -and $status.final_asset_id) {
        Write-Host "  timed out polling but job has final asset (status=$($status.status)); continuing download" -ForegroundColor Yellow
        return $status
    }
    throw "Timed out waiting for TTS. Poll: GET $script:BaseUrl/audio-jobs/$AudioJobId"
}

function Save-FinalAudio {
    param(
        [string]$AudioJobId,
        [string]$TranscriptId,
        [string]$DestDir,
        [object]$JobStatus = $null
    )
    Write-Step "Downloading audio..."

    if (-not (Test-Path $DestDir)) {
        New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
    }

    $outFile = Join-Path $DestDir "final-$AudioJobId.mp3"
    $masterFile = $null
    $manifestResponse = $null
    $finalObjectKey = $null
    $manifestUrl = $null
    $manifestPayload = $null

    try {
        $manifestResponse = Invoke-Api -Path "/audio-jobs/$AudioJobId/manifest?include_urls=true"
        $manifestPayload = $manifestResponse.manifest
        $finalObjectKey = $manifestResponse.final_object_key

        if (-not $manifestResponse.final_url) {
            throw "Manifest has no final_url"
        }
        Invoke-WebRequest -Uri $manifestResponse.final_url -OutFile $outFile -UseBasicParsing | Out-Null

        if ($manifestResponse.master_url) {
            $masterFile = Join-Path $DestDir "master-$AudioJobId.mp3"
            Invoke-WebRequest -Uri $manifestResponse.master_url -OutFile $masterFile -UseBasicParsing | Out-Null
        }
        $manifestUrl = $manifestResponse.manifest_url
    } catch {
        Write-Host "  manifest download unavailable ($($_.Exception.Message)); using S3 final key fallback" -ForegroundColor Yellow
        if (-not $JobStatus -or -not $JobStatus.final_asset_id) {
            throw "No manifest and no final_asset_id on job status"
        }
        $bucket = Resolve-TtsAudioBucket
        $finalObjectKey = "$TenantId/$TranscriptId/$AudioJobId/final/final.mp3"
        aws s3 cp "s3://$bucket/$finalObjectKey" $outFile | Out-Host
        if ($JobStatus.master_asset_id) {
            $masterKey = "$TenantId/$TranscriptId/$AudioJobId/final/master.mp3"
            $masterFile = Join-Path $DestDir "master-$AudioJobId.mp3"
            aws s3 cp "s3://$bucket/$masterKey" $masterFile | Out-Host
        }
        if ($null -ne $JobStatus.pause_hold_count) {
            Write-Host ("  pause holds (API): {0} totaling {1}s" -f `
                $JobStatus.pause_hold_count, $JobStatus.pause_total_hold_seconds) -ForegroundColor Cyan
        }
    }

    $sizeKb = [math]::Round((Get-Item $outFile).Length / 1KB, 1)
    Write-Host "  saved: $outFile ($sizeKb KB)" -ForegroundColor Green

    if ($manifestPayload) {
        Write-Host "  chunks in manifest: $($manifestPayload.chunk_count)"
        if ($manifestPayload.total_duration_ms) {
            $sec = [math]::Round($manifestPayload.total_duration_ms / 1000, 1)
            Write-Host "  duration (manifest speech est): ${sec}s"
        }
        if ($manifestPayload.pause_plan_summary) {
            $ps = $manifestPayload.pause_plan_summary
            Write-Host ("  pause holds: {0} totaling {1}s (policy={2})" -f `
                $ps.hold_count, $ps.total_hold_seconds, $ps.policy_version) -ForegroundColor Cyan
        } else {
            Write-Host "  pause_plan_summary: (none in manifest)" -ForegroundColor Yellow
        }
    }

    if ($masterFile -and (Test-Path $masterFile)) {
        $masterKb = [math]::Round((Get-Item $masterFile).Length / 1KB, 1)
        Write-Host ("  saved master: {0} ({1} KB)" -f $masterFile, $masterKb) -ForegroundColor Green
    }

    return @{
        LocalPath       = $outFile
        MasterPath      = $masterFile
        Manifest        = $manifestPayload
        FinalObjectKey  = $finalObjectKey
        ManifestUrl     = $manifestUrl
    }
}

function Test-AudioJobRecoverable {
    param([object]$Status)
    return [bool]$Status.final_asset_id
}

function Test-MixFailureError {
    param([object]$Status)
    $err = [string]$Status.last_error
    return ($err -match "background mix|No space left|ffmpeg")
}

function Invoke-LocalBackgroundMix {
    param(
        [string]$FinalPath,
        [string]$AudioJobId,
        [string]$DestDir
    )
    $bedPath = Join-Path $root "library\calm_ambient_01.mp3"
    if (-not (Test-Path $bedPath)) {
        $bucket = Resolve-TtsAudioBucket
        if (-not (Test-Path (Join-Path $root "library"))) {
            New-Item -ItemType Directory -Path (Join-Path $root "library") -Force | Out-Null
        }
        Write-Host "  fetching bed track from s3://$bucket/background/calm_ambient_01.mp3"
        aws s3 cp "s3://$bucket/background/calm_ambient_01.mp3" $bedPath | Out-Host
    }
    $masterOut = Join-Path $DestDir "master-$AudioJobId.mp3"
    $python = Join-Path $root ".venv\Scripts\python.exe"
    if (-not (Test-Path $python)) {
        $python = "python"
    }
    Write-Step "Local background mix (same engine as Lambda; use when AWS mix failed)"
    & $python (Join-Path $root "scripts\mix_background_smoke.py") `
        --narration $FinalPath `
        --bed $bedPath `
        --out $masterOut
    if ($LASTEXITCODE -ne 0) {
        throw "Local background mix failed (exit $LASTEXITCODE)"
    }
    return $masterOut
}

function Test-MixRetryWarranted {
    param([object]$Status)
    if (-not $Status.final_asset_id) { return $false }
    if ($Status.master_asset_id) { return $false }
    if ($Status.status -notin @("PARTIALLY_FAILED", "REVIEW_REQUIRED")) { return $false }
    return (Test-MixFailureError -Status $Status)
}

# --- main ---

$ApiKey = Resolve-ApiKey -Override $ApiKey
if (-not $ApiBase) {
    $ApiBase = $env:CREATIVE_AGENT_API_GATEWAY_URL
}
if (-not $ApiBase) {
    $ApiBase = "https://vwhmjhoym3.execute-api.us-east-1.amazonaws.com"
}
if (-not $OutputDir) {
    $OutputDir = Join-Path $root "output"
}

$script:BaseUrl = $ApiBase.TrimEnd("/")
$script:Headers = @{
    "X-API-Key"   = (Sanitize-HeaderValue $ApiKey)
    "X-Tenant-Id" = (Sanitize-HeaderValue $TenantId)
}

Write-Host "Creative Agent - full pipeline" -ForegroundColor White
Write-Host "  API:      $script:BaseUrl"
Write-Host "  tenant:   $TenantId"
Write-Host "  output:   $OutputDir"

$enhanceDeadline = (Get-Date).AddMinutes($EnhancementTimeoutMinutes)
$ttsDeadline = (Get-Date).AddMinutes($TtsTimeoutMinutes)

if ($TranscriptId) {
    Write-Step "Using existing transcript $TranscriptId"
    $tx = Invoke-Api -Path "/transcripts/$TranscriptId"
    if ($tx.status -ne "ENHANCED") {
        if ($tx.status -eq "PENDING_ENHANCEMENT" -or $tx.status -eq "ENHANCING") {
            Wait-TranscriptEnhanced -Id $TranscriptId -Deadline $enhanceDeadline | Out-Null
        } else {
            throw "Transcript status is $($tx.status); need ENHANCED (or in-progress enhancement)"
        }
    }
    $transcriptId = $TranscriptId
} else {
    $transcriptId = Start-Composer -Deadline $enhanceDeadline
}

$versionId = Get-EnhancedVersionId -Id $transcriptId
Write-Host "  enhanced version: $versionId"

$job = Start-AudioJob -Id $transcriptId -VersionId $versionId
$finalStatus = Wait-AudioJob -AudioJobId $job.audio_job_id -Deadline $ttsDeadline

if ((-not $NoAutoRetryMix) -and (Test-MixRetryWarranted -Status $finalStatus)) {
    Write-Step "Re-enqueueing TTS worker for mix-only replay (deploy worker with tts_lambda_ephemeral_storage_mb >= 2048 first)"
    $ephemeral = aws lambda get-function-configuration --function-name creative-agent-dev-tts-worker --query "EphemeralStorage.Size" --output text 2>$null
    if ($ephemeral -and [int]$ephemeral -lt 2048) {
        Write-Host "  WARNING: Lambda ephemeral storage is ${ephemeral}MB (need >= 2048). Run: cd infra\terraform; terraform apply" -ForegroundColor Red
    }
    Start-AudioJob -Id $transcriptId -VersionId $versionId | Out-Null
    $finalStatus = Wait-AudioJob -AudioJobId $job.audio_job_id -Deadline $ttsDeadline
}

$download = Save-FinalAudio -AudioJobId $job.audio_job_id -TranscriptId $transcriptId -DestDir $OutputDir -JobStatus $finalStatus

if (-not $download.MasterPath -and (Test-Path $download.LocalPath) -and (Test-MixFailureError -Status $finalStatus)) {
    $localMaster = Invoke-LocalBackgroundMix -FinalPath $download.LocalPath -AudioJobId $job.audio_job_id -DestDir $OutputDir
    $download.MasterPath = $localMaster
}

Write-Host ""
Write-Host "=== PIPELINE COMPLETE ===" -ForegroundColor Green
Write-Host "transcript_id : $transcriptId"
Write-Host "audio_job_id  : $($job.audio_job_id)"
Write-Host "job status    : $($finalStatus.status)"
Write-Host "final mp3     : $($download.LocalPath)"
if ($download.MasterPath) {
    Write-Host "master mp3    : $($download.MasterPath)"
}

Write-Step "Pause E2E verify (automated checks + listening checklist)"
$verifyArgs = @(
    "scripts/pause_e2e_verify.py",
    "--audio-job-id", "$($job.audio_job_id)",
    "--final-mp3", "$($download.LocalPath)"
)
if ($download.MasterPath) {
    $verifyArgs += @("--master-mp3", "$($download.MasterPath)")
}
try {
    & python @verifyArgs
} catch {
    Write-Host "  pause_e2e_verify.py skipped: $_" -ForegroundColor Yellow
}

if ($OpenAudio) {
    $openPath = $download.LocalPath
    if ($download.MasterPath -and (Test-Path $download.MasterPath)) {
        $openPath = $download.MasterPath
    }
    Start-Process $openPath
}

return [pscustomobject]@{
    transcript_id     = $transcriptId
    transcript_version_id = $versionId
    audio_job_id      = $job.audio_job_id
    job_status        = $finalStatus.status
    completed_chunks  = $finalStatus.completed_chunks
    total_chunks      = $finalStatus.total_chunks
    failed_chunks     = $finalStatus.failed_chunks
    local_mp3_path    = $download.LocalPath
    master_mp3_path   = $download.MasterPath
    final_object_key  = $download.FinalObjectKey
    manifest          = $download.Manifest
}
