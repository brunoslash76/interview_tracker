#!/usr/bin/env pwsh
param(
    [ValidateSet("quick", "full")]
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

if ($Mode -eq "quick") {
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
