# Refresh PATH so WinGet-installed terraform is visible in this session.
$wingetLinks = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
if (Test-Path $wingetLinks) {
    $env:Path = "$wingetLinks;$env:Path"
}

if (-not (Get-Command terraform -ErrorAction SilentlyContinue)) {
    Write-Error "terraform not found. Install: winget install Hashicorp.Terraform --source winget"
    exit 1
}

& terraform @args
