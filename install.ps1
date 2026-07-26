#Requires -Version 5.1
<#
Interview Tracker — Windows installer.
Run from the project folder:  .\install.ps1
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path (Join-Path $Root "bin\scan_gmail.py"))) {
    throw "Run install.ps1 from the Interview Tracker repository root."
}

if ($env:OS -notlike "*Windows*") {
    throw "install.ps1 requires native Windows."
}

$DataDir = if ($env:INTERVIEW_TRACKER_DATA_DIR) {
    $env:INTERVIEW_TRACKER_DATA_DIR
} else {
    Join-Path $env:LOCALAPPDATA "InterviewTracker"
}

function Find-Python {
    foreach ($candidate in @("py -3", "python", "python3")) {
        try {
            $parts = $candidate.Split(" ")
            if ($parts.Count -eq 2) {
                & $parts[0] $parts[1] -c "import sys; print(sys.executable)" | Out-Null
                if ($LASTEXITCODE -eq 0) { return $parts }
            } else {
                & $candidate -c "import sys; print(sys.executable)" | Out-Null
                if ($LASTEXITCODE -eq 0) { return @($candidate) }
            }
        } catch {
            continue
        }
    }
    throw "Python 3 was not found. Install Python 3.11+ and retry."
}

function Invoke-Python {
    param([string[]]$Base, [string[]]$Args)
    if ($Base.Count -eq 2) {
        & $Base[0] $Base[1] @Args
    } else {
        & $Base[0] @Args
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Args -join ' ')"
    }
}

Write-Host "Installing Interview Tracker from $Root"
Write-Host "Private data directory: $DataDir"

$pythonBase = Find-Python
$venvPython = Join-Path $Root "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating project virtual environment…"
    Invoke-Python $pythonBase @("-m", "venv", (Join-Path $Root "venv"))
}

Write-Host "Installing Windows runtime dependencies…"
Invoke-Python @($venvPython) @("-m", "pip", "install", "--quiet", "--upgrade", "pip")
Invoke-Python @($venvPython) @("-m", "pip", "install", "--quiet", "-r", (Join-Path $Root "requirements-windows.txt"))
Invoke-Python @($venvPython) @("-m", "pip", "install", "--quiet", "-r", (Join-Path $Root "requirements-dev.txt"))

New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "logs") | Out-Null

$env:INTERVIEW_TRACKER_DATA_DIR = $DataDir
Write-Host "Initializing private database…"
Invoke-Python @($venvPython) @(
    (Join-Path $Root "bin\database.py"),
    "--db", (Join-Path $DataDir "interview_tracker.sqlite3"),
    "init"
) | Out-Null

Write-Host "Checking for legacy private data…"
Invoke-Python @($venvPython) @(Join-Path $Root "bin\migrate_json_to_sqlite.py")

$configExample = Join-Path $Root "config.env.example"
$configDest = Join-Path $DataDir "config.env"
if ((Test-Path $configExample) -and -not (Test-Path $configDest)) {
    Copy-Item $configExample $configDest
    Write-Host "Created private config: $configDest"
}

Invoke-Python @($venvPython) @(Join-Path $Root "bin\merge_interviews.py") | Out-Null

Write-Host "Syncing Gmail scan scheduler from SQLite…"
Invoke-Python @($venvPython) @(
    (Join-Path $Root "bin\scheduler.py"),
    "sync",
    "--root", $Root,
    "--home", $env:USERPROFILE,
    "--data-dir", $DataDir,
    "--db", (Join-Path $DataDir "interview_tracker.sqlite3")
)

Write-Host "Registering system tray at logon…"
Invoke-Python @($venvPython) @(
    "-c",
    "import scheduler_windows as s; from pathlib import Path; s.sync_tray_task(Path(r'$Root'), Path(r'$DataDir'))"
)

if (Test-Path (Join-Path $Root "scripts\install_git_hooks.sh")) {
    Write-Host "Configuring repository Git hooks…"
    bash (Join-Path $Root "scripts\install_git_hooks.sh")
}

Write-Host ""
Write-Host "Installed. Configure scan times in Settings (tray icon → Settings)."
Write-Host ""
Write-Host "  Scan now:       $venvPython $(Join-Path $Root 'bin\scan_gmail.py')"
Write-Host "  Open dashboard: tray icon → Open Full Dashboard"
Write-Host "  Task status:    schtasks /Query /TN InterviewTracker\GmailScan"
Write-Host "  Logs:           Get-Content -Wait $(Join-Path $DataDir 'logs\scan.log')"
Write-Host ""
Write-Host "  If the Gmail scan can't find the CLI, set CLAUDE_BIN in $configDest."
