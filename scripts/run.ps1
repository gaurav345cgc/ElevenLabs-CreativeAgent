# One command: full pipeline (compose -> enhance -> TTS -> final MP3).
# Resumes automatically if the last run stopped with an error.
#
# Usage:
#   .\scripts\run.ps1
#   .\scripts\run.ps1 -Fresh          # ignore saved checkpoint, start new
#   .\scripts\run.ps1 -AcceptPartial  # download partial audio on TTS review

param(
    [int]$DurationMinutes = 5,
    [string]$ApiKey = "",
    [string]$ApiBase = "",
    [string]$TranscriptId = "",
    [string]$AudioJobId = "",
    [string]$OutputDir = "",
    [switch]$Fresh,
    [switch]$AcceptPartial
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$argsList = @("-m", "pipeline_orchestrator", "--duration-minutes", $DurationMinutes)
if ($ApiKey) { $argsList += @("--api-key", $ApiKey) }
if ($ApiBase) { $argsList += @("--api-base", $ApiBase) }
if ($TranscriptId) { $argsList += @("--transcript-id", $TranscriptId) }
if ($AudioJobId) { $argsList += @("--audio-job-id", $AudioJobId) }
if ($OutputDir) { $argsList += @("--output-dir", $OutputDir) }
if ($Fresh) { $argsList += "--fresh" }
if ($AcceptPartial) { $argsList += "--accept-partial" }

Push-Location $root
try {
    & $python @argsList
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
