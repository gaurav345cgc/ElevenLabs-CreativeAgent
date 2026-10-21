# Validate Agent 1 transcript against pattern index + examples corpus.
#
# Usage:
#   .\scripts\validate_transcript.ps1 -DryRun
#   .\scripts\validate_transcript.ps1 -TranscriptId "21b6a813-4b98-470b-82f3-606c68295629"

param(
    [string]$TranscriptId = "",
    [switch]$DryRun,
    [switch]$Rules,
    [switch]$OpenAI,
    [int]$DurationMinutes = 5
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$argsList = @("scripts/validate_transcript.py")
if ($DryRun) { $argsList += "--dry-run" }
if ($TranscriptId) { $argsList += @("--transcript-id", $TranscriptId) }
if ($Rules) { $argsList += "--rules" }
if ($OpenAI) { $argsList += "--openai" }
if ($DurationMinutes -ne 5) { $argsList += @("--duration-minutes", $DurationMinutes) }

Push-Location $root
try {
    & $python @argsList
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
