# LangGraph pipeline orchestrator (compose -> enhance -> TTS with per-stage retry)
#
# Usage:
#   .\scripts\run_orchestrator.ps1
#   .\scripts\run_orchestrator.ps1 -TranscriptId "<uuid>"
#   .\scripts\run_orchestrator.ps1 -AcceptPartial

param(
    [string]$TenantId = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    [int]$DurationMinutes = 5,
    [string]$ApiKey = "",
    [string]$ApiBase = "",
    [string]$TranscriptId = "",
    [string]$AudioJobId = "",
    [string]$OutputDir = "",
    [switch]$AcceptPartial,
    [switch]$SkipTts,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$argsList = @("-m", "pipeline_orchestrator", "--tenant-id", $TenantId, "--duration-minutes", $DurationMinutes)
if ($ApiKey) { $argsList += @("--api-key", $ApiKey) }
if ($ApiBase) { $argsList += @("--api-base", $ApiBase) }
if ($TranscriptId) { $argsList += @("--transcript-id", $TranscriptId) }
if ($AudioJobId) { $argsList += @("--audio-job-id", $AudioJobId) }
if ($OutputDir) { $argsList += @("--output-dir", $OutputDir) }
if ($AcceptPartial) { $argsList += "--accept-partial" }
if ($SkipTts) { $argsList += "--skip-tts" }
if ($Json) { $argsList += "--json" }

Push-Location $root
try {
    & $python @argsList
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
