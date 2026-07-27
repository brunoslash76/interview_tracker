#!/usr/bin/env pwsh
param(
    [ValidateSet("quick", "commit", "full")]
    [string]$Mode = "quick"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (Test-Path (Join-Path $Root "venv\Scripts\python.exe")) {
    $Python = Join-Path $Root "venv\Scripts\python.exe"
} else {
    $Python = (Get-Command python -ErrorAction Stop).Source
}

Write-Host "Validating dashboard component harness…"
node --check tests/dashboard_component_harness.js

if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) {
    Push-Location (Join-Path $Root "frontend")
    npm ci
    Pop-Location
}
Write-Host "Testing and building React frontend…"
Push-Location (Join-Path $Root "frontend")
if ($Mode -eq "full") {
    npm run test:coverage
    npm run build
    & $Python scripts/generate_coverage_badge.py `
        frontend/coverage/coverage-summary.json frontend-coverage.svg --label frontend
    if (git diff --quiet HEAD -- frontend-coverage.svg) { } else {
        throw "frontend-coverage.svg changed. Commit the refreshed README badge."
    }
    npm run build-storybook
    $storyJob = Start-Job { param($dir) Set-Location $dir; python -m http.server 6007 --directory storybook-static } -ArgumentList (Get-Location)
    Start-Sleep -Seconds 2
    npm run test:storybook -- --url http://127.0.0.1:6007
    Stop-Job $storyJob | Out-Null
    Remove-Job $storyJob | Out-Null
} else {
    npm test
    npm run build
}
Pop-Location

if ($Mode -eq "commit") {
    Write-Host "Running Playwright E2E (Chromium)…"
    if (-not (& $Python -c "import uvicorn" 2>$null)) {
        & $Python -m pip install -r requirements-dev.txt
    }
    Push-Location (Join-Path $Root "frontend")
    npx playwright install --with-deps chromium
    npm run test:e2e -- --project=chromium
    Pop-Location
}

if ($Mode -eq "quick" -or $Mode -eq "commit") {
    Write-Host "Running unit and component tests…"
    & $Python -m unittest discover -s tests -p "test_*_unit.py" -v
} else {
    if (-not (& $Python -m coverage --version 2>$null)) {
        throw "coverage.py is required for full checks. pip install -r requirements-dev.txt"
    }
    Write-Host "Running unit and component tests with coverage…"
    & $Python -m coverage erase
    & $Python -m coverage run -m unittest discover -s tests -p "test_*_unit.py" -v
    Write-Host "Running integration tests with coverage…"
    & $Python -m coverage run --append -m unittest discover -s tests -p "test_integration_*.py" -v
    & $Python -m coverage report --fail-under=80
    & $Python -m coverage xml
}

Write-Host "All $Mode checks passed."
