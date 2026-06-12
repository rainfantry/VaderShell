# VaderShell - one-step setup: venv, dependencies, .env, prereq checks.
# Run from this folder:  .\setup.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "== VaderShell setup ==" -ForegroundColor Cyan

# 1. Python on PATH
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "Python not found on PATH. Install Python 3.11+ and re-run." -ForegroundColor Red
    exit 1
}
Write-Host "python : $($py.Source)"

# 2. Virtual environment
$venv = Join-Path $root ".venv"
if (Test-Path $venv) {
    Write-Host ".venv   : exists"
} else {
    Write-Host ".venv   : creating..."
    python -m venv $venv
}
$vpy = Join-Path $venv "Scripts\python.exe"

# 3. Dependencies
Write-Host "deps    : installing from requirements.txt..."
& $vpy -m pip install --quiet --upgrade pip
& $vpy -m pip install --quiet -r (Join-Path $root "requirements.txt")

# 4. .env from template (never overwrite an existing one)
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    Write-Host ".env    : exists (left untouched)"
} else {
    Copy-Item (Join-Path $root ".env.example") $envFile
    Write-Host ".env    : created from .env.example - edit it with your values" -ForegroundColor Yellow
}

# 5. Claude CLI (the default brain) - warn, don't fail
$claude = Get-Command claude -ErrorAction SilentlyContinue
if ($claude) {
    Write-Host "claude  : $($claude.Source)"
} else {
    Write-Host "claude  : NOT found - install Claude Code and run 'claude' then /login" -ForegroundColor Yellow
    Write-Host "          (required for the default 'claude' brain; not needed for kimi/openrouter)"
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "  terminal : .\22div.ps1"
Write-Host "  gateway  : .\gateway.ps1"
