# Run a plain-language health audit when the pipeline stops or before a new batch.
#
# Usage:
#   .\scripts\audit.ps1
#   .\scripts\audit.ps1 -SaveReport    # also writes output\audit-report.txt

param(
    [string]$OutputDir = "",
    [switch]$SaveReport,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$argsList = @("scripts/audit_pipeline.py")
if ($OutputDir) { $argsList += @("--output-dir", $OutputDir) }
if ($Json) { $argsList += "--json" }
if ($SaveReport) { $argsList += @("--save", "output/audit-report.txt") }

Push-Location $root
try {
    & $python @argsList
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
