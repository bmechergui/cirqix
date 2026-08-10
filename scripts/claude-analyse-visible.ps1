# Lance Claude en analyse read-only — à lancer DANS le terminal VS Code (Ctrl+`)
# Usage:
#   .\scripts\claude-analyse-visible.ps1

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repo

$out = Join-Path $env:TEMP "claude-visible-analyse"
New-Item -ItemType Directory -Path $out -Force | Out-Null
$briefPath = Join-Path $out "brief.txt"
$logPath = Join-Path $out "claude-output.log"

if (-not (Test-Path $briefPath)) {
  Write-Host "Brief manquant: $briefPath" -ForegroundColor Red
  Write-Host "Le brief doit exister (Grok le prépare, ou recrée-le)."
  exit 1
}

Write-Host "============================================" -ForegroundColor Yellow
Write-Host " CLAUDE ANALYSE CIRQIX (terminal VS Code)  " -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Yellow
Write-Host "Repo : $repo"
Write-Host "Brief: $briefPath"
Write-Host "Log  : $logPath"
Write-Host "Mode : claude -p --permission-mode plan (read-only)"
Write-Host ""

Get-Content -Raw $briefPath | claude -p --permission-mode plan --output-format text 2>&1 | Tee-Object -FilePath $logPath
$code = $LASTEXITCODE

Write-Host ""
Write-Host "=== TERMINE exit=$code ===" -ForegroundColor Green
Write-Host "Rapport aussi dans: $logPath"
exit $code
