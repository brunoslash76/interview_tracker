# Interview Tracker

[![Tests](https://github.com/brunoslash76/interview_tracker/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/brunoslash76/interview_tracker/actions/workflows/tests.yml)
![Python coverage](coverage.svg)

Interview Tracker is a local automation for **macOS, Windows, and Linux** that scans Gmail
for job-interview threads, merges structured results into a private SQLite
database, renders an HTML dashboard, and sends change-aware notifications. On
macOS, a lightweight Python menu-bar app shows current counts and can start a
scan; on Windows and Linux, a system-tray app provides the same controls.

The repository contains code and portable templates only. User records,
configuration, generated pages, logs, and backups live outside the clone.

## Supported platforms

Interview Tracker ships **native installers** for three desktop environments.
All platforms share the same SQLite store, dashboard, settings UI (via the local
loopback server), and **`bin/scan_gmail.py`** scan pipeline; only background
scheduling, notifications, and the status UI differ.

| | **macOS** | **Windows** | **Linux** |
|---|-----------|-------------|-----------|
| **Installer** | `bash install.sh` | `powershell -ExecutionPolicy Bypass -File .\install.ps1` | `bash install-linux.sh` (or `bash install.sh`) |
| **Status UI** | Menu bar (`InterviewTracker.app` + rumps) | System tray (`bin/tray_app.py`) | System tray (`bin/tray_app.py`) |
| **Scheduled scans** | launchd `com.interview-tracker.scheduler` | Task Scheduler `InterviewTracker\GmailScan` | systemd user `interview-tracker-scan.timer` |
| **Change notifications** | launchd `WatchPaths` → `notifier.py` | Tray polls DB + toast; optional ntfy | systemd `.path` on SQLite → `notifier.py` |
| **Default data dir** | `~/Library/Application Support/InterviewTracker` | `%LOCALAPPDATA%\InterviewTracker` | `~/.local/share/InterviewTracker` (or `$XDG_DATA_HOME/…`) |
| **Override data dir** | `INTERVIEW_TRACKER_DATA_DIR` (same on all OSes) | | |

**Quick start by OS**

- **macOS:** clone the repo → [Set up Claude](#set-up-claude-required-before-gmail-scans) → `bash install.sh` → open **InterviewTracker.app** from the menu bar.
- **Windows:** clone → set up Claude → `install.ps1` → tray icon appears at logon (or run `.\venv\Scripts\python.exe .\bin\tray_app.py` once).
- **Linux:** install `python3-venv` and optionally `libnotify-bin` → set up Claude → `bash install-linux.sh` → tray starts via `interview-tracker-tray.service` when you log in to a graphical session.

On every OS, open **Settings** from the tray/menu to set daily scan times (up to
five). Saving applies the schedule to SQLite and reloads the platform scheduler
(launchd plist, Task Scheduler task, or systemd timer).

## Current architecture

All platforms follow the same core pipeline; background integration differs as
in [Supported platforms](#supported-platforms).

1. A **scheduled or manual scan** runs `bin/scan_gmail.py` (wrapper: `bin/scan_gmail.sh` on Unix) at times stored in SQLite **Settings**, or when you choose **Refresh Now** / **Scan Gmail now**.
2. The scan runs the **Claude CLI** headlessly with only the Gmail thread-search and thread-read MCP tools. Scans started less than 30 minutes after the previous success use an exact Gmail epoch boundary from the newest message Claude actually read. Older runs use a five-day overlap; the first scan looks back 120 days.
3. Claude returns schema-constrained JSON; `bin/merge_interviews.py` merges it into SQLite and regenerates the private dashboard.
4. **Notifications** compare the latest scan summary hash to `.last_notified_hash`. Unchanged data stays silent. Changed data triggers a desktop alert (and optional ntfy push when configured).
5. The **menu bar (macOS)** or **system tray (Windows/Linux)** app starts a loopback-only web server, reads SQLite, refreshes counts when the database changes, and opens dashboard/settings in the browser.

Platform specifics:

- **macOS:** launchd runs the scan timer, watches the SQLite file for notifier events, and starts `InterviewTracker.app` at login.
- **Windows:** Task Scheduler runs scans and starts the tray at logon; the tray may poll the DB for UI updates (scheduled notifier is not separate from tray on Windows).
- **Linux:** systemd user units run the scan timer, watch the SQLite file (`interview-tracker-notifier.path`), and start the tray after the graphical session.

SQLite uses rollback-journal mode so committed writes update the main database file (important for macOS `WatchPaths` and Linux `.path` units). The tray/menu **60-second** file check refreshes the UI only; it does not scan Gmail.

Portable templates: **`launchd/`** (macOS), Task Scheduler XML under **`%LOCALAPPDATA%\InterviewTracker\tasks\`** (Windows), and **`systemd/`** unit files under the private data directory (Linux, installed to `~/.config/systemd/user/`).

## Daily use by OS

### macOS

- **Menu bar:** launch `InterviewTracker.app` (installed at login via launchd). Use **Open Full Dashboard**, **Settings**, and **Refresh Now**.
- **Manual scan:** `bash bin/scan_gmail.sh` or menu **Refresh Now**.
- **Logs:** `tail -f "$HOME/Library/Application Support/InterviewTracker/logs/scan.log"`
- **Agent status:** `launchctl list | grep interview-tracker`

### Windows

- **Tray:** appears after install/logon (`InterviewTracker\Tray`). Same menu actions as macOS (dashboard, settings, refresh, exit).
- **Manual scan:** `.\venv\Scripts\python.exe .\bin\scan_gmail.py`
- **Logs:** `%LOCALAPPDATA%\InterviewTracker\logs\scan.log`
- **Tasks:** `schtasks /Query /TN InterviewTracker\GmailScan` and `InterviewTracker\Tray`
- **Re-run tray once:** `.\venv\Scripts\python.exe .\bin\tray_app.py`

### Linux

- **Tray:** `interview-tracker-tray.service` (user systemd). Requires a graphical session; Wayland tray support depends on your desktop and pystray/AppIndicator packages.
- **Manual scan:** `./venv/bin/python3 ./bin/scan_gmail.py`
- **Logs:** `~/.local/share/InterviewTracker/logs/scan.log` (or under your `INTERVIEW_TRACKER_DATA_DIR`)
- **Units:** `systemctl --user status interview-tracker-scan.timer interview-tracker-tray.service interview-tracker-notifier.path`
- **Journal:** `journalctl --user -u interview-tracker-tray.service -f`
- **Scans after logout (no tray):** optional `loginctl enable-linger "$USER"` so user timers can run without an active session; the tray still needs you logged in graphically.

### All platforms

- **Settings / dashboard:** start the tray or menu app so the loopback server runs, then open **Settings** or **Open Full Dashboard**. CSRF-protected writes require that server; the static `dashboard.html` file alone cannot save settings.
- **Override install location:** set `INTERVIEW_TRACKER_DATA_DIR` before install, then re-run the installer for your OS so schedulers pick up the path.

## Prerequisites

### macOS

- macOS 11 or later
- `/usr/bin/python3`, including `venv` and `pip`
- **Claude CLI** with Gmail access configured (see [Set up Claude](#set-up-claude-required-before-gmail-scans) below)
- Network access during installation for `rumps` and `pyobjc`
- Optional: `brew install terminal-notifier` for more reliable Mac alerts
- Optional: the ntfy app and a private topic for phone/watch pushes

### Windows

- Windows 10 or later
- Python 3.11+ (`py -3` or `python` on PATH)
- **Claude CLI** with Gmail access (same MCP tools as macOS)
- Network access during installation for `pystray`, `Pillow`, and `win10toast`
- Optional: ntfy topic in private `config.env` for phone pushes
- Task Scheduler runs in the **current user** context (no administrator required)

### Linux

- A mainstream distro with **systemd** and `systemctl --user`
- Python 3.11+ with `venv` and `pip`
- **Claude CLI** with Gmail MCP (same tools as macOS)
- `pip install -r requirements-linux.txt` (pystray, Pillow) via the installer
- Optional: `libnotify-bin` for `notify-send`; ntfy topic in `config.env`
- Graphical session for the system tray (Wayland tray support varies by distro)

## Set up Claude (required before Gmail scans)

Interview Tracker does **not** call the Gmail API itself. Every scan runs the
**Claude CLI** headlessly and uses Claude’s Gmail MCP tools to search threads and
read message content. Complete this setup **before** you rely on scheduled scans
or **Refresh Now**; you can still run your platform installer to set up agents and
the menu/tray app, but scans will fail until Claude is ready.

### 1. Install the Claude CLI

Install Anthropic’s Claude CLI using the method in the current
[Claude Code documentation](https://docs.anthropic.com/en/docs/claude-code/overview)
(official installer or package manager on your OS).

Confirm the binary is on your PATH:

```sh
which claude    # macOS / Linux
claude --version
```

On Windows (PowerShell):

```powershell
Get-Command claude
claude --version
```

If the binary lives outside the PATH seen by scheduled jobs (often `~/.local/bin`
on Unix or a custom install folder on Windows), set `CLAUDE_BIN` in private
`config.env` after installation ([step 5](#5-point-background-jobs-at-claude-if-needed)).

### 2. Sign in to Claude

Log in from the terminal so non-interactive scans can run:

```sh
claude
```

Follow the prompts until the CLI is authenticated. Use the same flow recommended
in Anthropic’s docs for your CLI version (browser login, API key, or subscription,
depending on how your install is configured).

### 3. Connect Gmail to Claude

The scan entrypoint is **`bin/scan_gmail.py`** (see [Daily use by OS](#daily-use-by-os) for the command on your system).

- `mcp__claude_ai_Gmail__search_threads`
- `mcp__claude_ai_Gmail__get_thread`

In the **Claude desktop app or account settings**, connect **Gmail** (Google)
so Claude can access the mailbox you use for interview email. Sign in with the
**Google account that actually receives** recruiter and interview messages.

The optional **email filter** in Interview Tracker Settings only narrows search
queries; it does **not** switch Google accounts. The mailbox Claude can read is
whatever you connected in Claude.

### 4. Verify Gmail access (recommended)

Run a quick interactive check that Claude can use Gmail tools (exact commands
depend on your CLI version). If interactive Gmail search works in Claude, the
headless scan is much more likely to succeed.

After you install Interview Tracker, run one manual scan from the repo root:

```sh
# macOS / Linux
bash bin/scan_gmail.sh
# or: ./venv/bin/python3 ./bin/scan_gmail.py
```

```powershell
# Windows
.\venv\Scripts\python.exe .\bin\scan_gmail.py
```

Then inspect the scan log in your [private data directory](#private-runtime-files) (`logs/scan.log`). You should see a completed scan, not `claude CLI not found` or MCP/tool errors.

### 5. Point background jobs at Claude (if needed)

Scheduled scans run with a **limited PATH** (launchd, Task Scheduler, or systemd).
If interactive scans work but scheduled ones fail, set the full path in private
`config.env`:

| OS | Typical config path |
|----|---------------------|
| macOS | `~/Library/Application Support/InterviewTracker/config.env` |
| Windows | `%LOCALAPPDATA%\InterviewTracker\config.env` |
| Linux | `~/.local/share/InterviewTracker/config.env` |

Example (use your path from `which claude` / `Get-Command claude`):

```sh
CLAUDE_BIN=/Users/you/.local/bin/claude
```

**macOS:** `open -e "$HOME/Library/Application Support/InterviewTracker/config.env"`

**Windows:** `notepad "$env:LOCALAPPDATA\InterviewTracker\config.env"`

**Linux:** `$EDITOR ~/.local/share/InterviewTracker/config.env`

Save the file, then run a manual scan again.

## Install

### macOS

```sh
git clone <repository-url> email-reader
cd email-reader
bash install.sh
```

`install.sh` on **macOS** runs the launchd installer; on **Linux** it delegates to
`install-linux.sh`; on **Git Bash/MSYS** it delegates to `install.ps1`.

The macOS installer:

- creates `~/Library/Application Support/InterviewTracker`;
- copies `config.env.example` to the private `config.env` if none exists;
- initializes SQLite and renders the initial dashboard;
- performs any legacy JSON migration described below;
- builds the repository-local `venv/` for the menu app;
- renders the portable plist templates into `~/Library/LaunchAgents`; and
- syncs the Gmail scheduler LaunchAgent from SQLite; and
- loads the scheduler, notifier, and menu-bar LaunchAgents.

### Windows

```powershell
git clone <repository-url> email-reader
cd email-reader
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

The Windows installer:

- creates `%LOCALAPPDATA%\InterviewTracker` (override with `INTERVIEW_TRACKER_DATA_DIR`);
- copies `config.env.example` to private `config.env` when missing;
- initializes SQLite and renders the initial dashboard;
- builds `venv\` and installs `requirements-windows.txt` (tray + notifications);
- registers Task Scheduler jobs `InterviewTracker\GmailScan` (daily scan times from SQLite)
  and `InterviewTracker\Tray` (system tray at logon, with restart on failure).

Manual scan:

```powershell
.\venv\Scripts\python.exe .\bin\scan_gmail.py
```

Task status:

```powershell
schtasks /Query /TN InterviewTracker\GmailScan
schtasks /Query /TN InterviewTracker\Tray
```

### Linux

```sh
git clone <repository-url> email-reader
cd email-reader
bash install-linux.sh
```

(`bash install.sh` on Linux delegates to the same script.)

The Linux installer:

- creates `~/.local/share/InterviewTracker` (or `$XDG_DATA_HOME/InterviewTracker`);
- copies `config.env.example` to private `config.env` when missing;
- initializes SQLite and renders the initial dashboard;
- builds `venv/` and installs `requirements-linux.txt` (pystray + Pillow);
- installs **systemd user units** for scan timer, DB-triggered notifier, and tray;
- enables `interview-tracker-scan.timer`, `interview-tracker-notifier.path`, and `interview-tracker-tray.service`.

Manual scan:

```sh
./venv/bin/python3 ./bin/scan_gmail.py
```

Unit status:

```sh
systemctl --user status interview-tracker-scan.timer
systemctl --user status interview-tracker-tray.service
journalctl --user -u interview-tracker-tray.service -f
```

Optional: `loginctl enable-linger "$USER"` so scheduled scans can run after you log out (tray still needs a graphical session).

Distro packages often needed: `python3-venv`, `libnotify-bin` (`notify-send`), and AppIndicator/system tray libraries for pystray on Wayland.

If you have not completed [Set up Claude](#set-up-claude-required-before-gmail-scans),
do that before expecting Gmail scans to work.

Edit private `config.env` after installation (paths in [step 5](#5-point-background-jobs-at-claude-if-needed)).
Set `CLAUDE_BIN` if background schedulers cannot find `claude`. Set `NTFY_TOPIC`
only if desired. Do not put secrets or private topic names in the repository.

## Private runtime files

Default locations by OS (override with `INTERVIEW_TRACKER_DATA_DIR` on any platform):

| OS | Default directory |
|----|-------------------|
| macOS | `~/Library/Application Support/InterviewTracker/` |
| Windows | `%LOCALAPPDATA%\InterviewTracker\` |
| Linux | `~/.local/share/InterviewTracker/` or `$XDG_DATA_HOME/InterviewTracker/` |

### macOS layout

```text
~/Library/Application Support/InterviewTracker/
├── interview_tracker.sqlite3  # live application and scan data
├── dashboard.html             # generated dashboard with embedded records
├── config.env                 # private runtime configuration (mode 0600)
├── .last_notified_hash        # notifier deduplication state
├── .http_port                 # loopback dashboard/settings server port
├── scan.lock/                 # present only while a Gmail scan is running
├── .ntfy_topic                # optional legacy/private topic fallback
├── backups/                   # verified migration and user-created backups
└── logs/                      # scan, notifier, scheduler, and menu logs
```

`raw_extraction.*` files may exist briefly during a scan and are removed on
exit. Set `INTERVIEW_TRACKER_DATA_DIR` to override the runtime directory for
manual or custom deployments; installed agents/tasks retain the location
configured at install time.

### Windows private data layout

```text
%LOCALAPPDATA%\InterviewTracker\
├── interview_tracker.sqlite3
├── dashboard.html
├── config.env
├── tasks\                     # exported Task Scheduler XML
├── .last_notified_hash
├── .http_port
├── scan.lock\
└── logs\
```

### Linux private data layout

```text
~/.local/share/InterviewTracker/   # or $XDG_DATA_HOME/InterviewTracker
├── interview_tracker.sqlite3
├── dashboard.html
├── config.env
├── systemd/                     # canonical unit files installed to ~/.config/systemd/user/
├── .last_notified_hash
├── .http_port
├── scan.lock/
└── logs/
```

## SQLite data model

Schema version 2 adds user settings on top of the interview store:

- `applications`, `scan_runs`, and `metadata` as before.
- `scan_schedule`: up to five unique daily scan times (`HH:MM`, local clock).
- `scan_preferences`: optional Gmail email filter for scan queries.

The supported stages are Initial Contact, Phone Screen, Technical Round, Final
Interview, and Offer. `status` remains free text. The generated dashboard is a
view of SQLite, not a second data store; edit `dashboard_template.html`, not the
generated private page.

## Settings page

Open **Settings** from the menu bar (macOS) or system tray (Windows/Linux), or
use **Settings** in the dashboard header when viewing it through the local server.

From Settings you can:

- add or remove up to five daily scan times using time inputs;
- save and apply the schedule, which updates SQLite and reloads the platform
  scheduler (launchd plist, Windows Task Scheduler task, or Linux systemd timer); and
- set an optional email address used to restrict Gmail searches to messages
  involving that address.

Important limitations:

- scan times use your **system local time zone**; behavior while the machine is
  asleep or logged out varies by OS (macOS launchd calendar, Windows Task Scheduler,
  Linux systemd with optional linger);
- removing all scan times disables automatic scans but keeps manual **Refresh
  Now** working;
- the email field is a Gmail search filter hint (`to:` / `from:` involvement),
  not an account switch — authenticate the correct Google account in the
  Claude CLI yourself;
- Claude's Gmail MCP tools enforce this filter only as well as the model follows
  the scan prompt.

The settings UI is served only on `127.0.0.1` by the menu/tray app. Writes require
a SameSite CSRF cookie and a matching request origin. If the menu/tray app is not
running, open the static private `dashboard.html` fallback instead (Settings
links will not work there).

When the loopback server is running, the dashboard header includes **Scan Gmail
now**. It starts the same `bin/scan_gmail.py` pipeline as **Refresh Now**, shows
a progress modal with live phase updates, and refreshes the table in place when
the scan finishes.

## Manual operation

See [Daily use by OS](#daily-use-by-os) for scan commands, logs, and scheduler status.

Shared CLI tools (run from the repo with your venv Python if installed):

```sh
python3 bin/database.py settings-json
python3 bin/database.py scan-config-json
python3 bin/scheduler.py sync --no-load
python3 bin/database.py records-json
python3 bin/database.py summary-json
python3 bin/database.py last-scan-date
python3 bin/merge_interviews.py       # re-render without scanning Gmail
```

### macOS only

```sh
open InterviewTracker.app
launchctl list | grep interview-tracker
launchctl kickstart -k "gui/$(id -u)/com.interview-tracker.scheduler"
tail -f "$HOME/Library/Application Support/InterviewTracker/logs/scan.log"
```

Pause or resume all LaunchAgents:

```sh
for name in scheduler notifier menubar; do
  launchctl bootout "gui/$(id -u)/com.interview-tracker.$name" 2>/dev/null || true
done

for name in scheduler notifier menubar; do
  launchctl bootstrap "gui/$(id -u)" \
    "$HOME/Library/LaunchAgents/com.interview-tracker.$name.plist"
done
```

### Windows only

```powershell
schtasks /Run /TN "InterviewTracker\GmailScan"
Get-Content -Wait "$env:LOCALAPPDATA\InterviewTracker\logs\scan.log"
```

### Linux only

```sh
systemctl --user start interview-tracker-scan.service   # one-shot scan now
systemctl --user reload-or-restart interview-tracker-tray.service
tail -f ~/.local/share/InterviewTracker/logs/scan.log
```

Disable platform scheduling without uninstalling (examples):

```powershell
# Windows
schtasks /Change /TN "InterviewTracker\GmailScan" /DISABLE
```

```sh
# Linux
systemctl --user disable --now interview-tracker-scan.timer
```

## Automatic legacy migration

On installation, a repository-local legacy `data/interviews.json`, if present,
is imported into the private SQLite database. The migration:

1. validates that the source is an array of records;
2. imports idempotently while preserving supplied timestamps;
3. verifies every non-null source field against the resulting database;
4. writes and byte-verifies
   `backups/interviews.pre-sqlite.<timestamp>.json`; and
5. only then removes the legacy JSON file.

Legacy `config.env`, `.ntfy_topic`, and `.last_notified_hash` files are also
copied to the private runtime location and verified. A conflicting private file
is preserved and the legacy copy is placed in `backups/`. The migration can be
run explicitly with:

```sh
python3 bin/migrate_json_to_sqlite.py
```

Use `--keep-source` to retain the source after a verified import.

## Export, backup, and reset

Export application records as JSON:

```sh
python3 bin/database.py records-json > interview-tracker-export.json
```

For a consistent backup of a live database, use Python's SQLite backup API
instead of copying the file:

```sh
python3 - <<'PY'
import datetime, pathlib, sqlite3
root = pathlib.Path.home() / "Library" / "Application Support" / "InterviewTracker"
dest = root / "backups" / f"interview-tracker.{datetime.datetime.now():%Y%m%d-%H%M%S}.sqlite3"
dest.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(root / "interview_tracker.sqlite3") as source:
    with sqlite3.connect(dest) as target:
        source.backup(target)
print(dest)
PY
```

To reset, first make a backup, pause all three agents, then remove only the live
database and generated state with Python:

```sh
python3 - <<'PY'
import pathlib
root = pathlib.Path.home() / "Library" / "Application Support" / "InterviewTracker"
for name in ("interview_tracker.sqlite3", "dashboard.html", ".last_notified_hash"):
    (root / name).unlink(missing_ok=True)
PY
bash install.sh
```

This preserves `config.env`, logs, and backups. Resetting permanently removes
live records once no usable backup remains.

## Portable launchd templates (macOS)

The checked-in `launchd/*.plist` files use `__ROOT__`, `__HOME__`, and
`__DATA_DIR__` placeholders; they contain no machine-specific paths.
`install.sh` XML-escapes the current values, writes the rendered plists under
`~/Library/LaunchAgents`, validates them with `plutil`, and loads them. Re-run
the macOS installer after moving the clone or changing the runtime directory.

On **Windows**, re-run `install.ps1` after moving the clone. On **Linux**, re-run
`install-linux.sh` (or `bash install.sh`).

## Reinstall and uninstall

| Goal | macOS | Windows | Linux |
|------|-------|---------|-------|
| **Reinstall / fix paths** | `bash install.sh` | `.\install.ps1` | `bash install-linux.sh` |
| **Stop background jobs** | `launchctl bootout` for each agent (see [Manual operation](#manual-operation)) | Disable or delete `InterviewTracker\*` tasks in Task Scheduler | `systemctl --user disable --now interview-tracker-scan.timer interview-tracker-notifier.path interview-tracker-tray.service` |
| **Remove user units** | Delete plists from `~/Library/LaunchAgents` | `schtasks /Delete /TN … /F` | Remove files from `~/.config/systemd/user/` and `daemon-reload` |

Private data under your platform data directory is **not** removed by reinstall;
delete that folder only if you intend to wipe records and config.

## Source tree and privacy

- `bin/` contains SQLite, scan, merge, notifier, migration, menu/tray, and scheduler code.
- `launchd/` contains portable macOS LaunchAgent templates.
- `install.sh`, `install-linux.sh`, and `install.ps1` are platform installers.
- `InterviewTracker.app/` is a minimal macOS menu-bar wrapper, not a self-contained
  distributable application.
- `dashboard_template.html` is the dashboard source.
- `tests/` contains standard-library integration tests.
- `data/` is only a legacy migration landing point.
- `venv/` is generated locally by the installer.

`.gitignore` excludes private configuration, notification state, logs,
repository-local JSON/SQLite data, generated dashboards, temporary files,
Python bytecode, and virtual environments. Before publishing changes, still
inspect `git status` and the staged diff; ignore rules do not remove files that
were already committed.

## Tests

The suite uses **stdlib `unittest`** for test cases and `coverage.py` for Python
line/branch measurement. Tests never call live Claude/Gmail, ntfy, or your private
`~/Library/Application Support/InterviewTracker` data. Integration tests set
temporary `HOME` and `INTERVIEW_TRACKER_DATA_DIR` and use fixture fakes under
[`tests/fixtures/`](/Users/bruno/Automations/email-reader/tests/fixtures/).

```sh
# All tests
python3 -m unittest discover -s tests -v

# Unit tests only
python3 -m unittest discover -s tests -p 'test_*_unit.py' -v

# Integration tests (shell/settings; macOS launchd paths in some tests)
python3 -m unittest discover -s tests -p 'test_integration_*.py' -v

# Platform-specific quick gates (also run in CI)
bash scripts/run_checks.sh full          # macOS: full + coverage
pwsh scripts/run_checks.ps1 quick        # Windows
bash scripts/run_checks_linux.sh quick # Linux
```

| Area | Files |
|------|--------|
| SQLite, settings, merge | `tests/test_database_unit.py` |
| Scheduler plist + rollback | `tests/test_scheduler_unit.py` |
| Loopback HTTP / CSRF | `tests/test_local_server_unit.py` |
| Legacy migration | `tests/test_migration_unit.py` |
| Dashboard render / CLI | `tests/test_merge_unit.py` |
| Menu-bar heuristics | `tests/test_menubar_logic_unit.py` |
| Scan, notifier, plist (Darwin) | `tests/test_integration_shell.py` |
| Settings → DB → plist | `tests/test_integration_settings.py` |
| Python scan pipeline | `tests/test_integration_scan.py` |
| Platform paths / systemd / Task Scheduler units | `tests/test_platform_unit.py`, `tests/test_scheduler_systemd_unit.py`, `tests/test_scheduler_windows_unit.py` |

CI runs on **`macos-latest`** (full gate + coverage), **`windows-latest`**, and
**`ubuntu-latest`** via
[`.github/workflows/tests.yml`](/Users/bruno/Automations/email-reader/.github/workflows/tests.yml).
The badge at the top reflects the macOS workflow on `main`.

Python coverage includes `bin/*.py`, except GUI entry points `bin/menubar_app.py`
and `bin/tray_app.py`; shared logic is covered in modules such as
`bin/menubar_logic.py`. The full macOS gate enforces at least **80%** combined
line/branch coverage and refreshes `coverage.svg`.
Dashboard JavaScript behavior is exercised separately by the Node component
harness and is not included in the Python percentage.

### Git hooks

The installer enables the version-controlled hooks in `.githooks/`:

- `pre-commit` runs shell/plist validation plus unit and dashboard component
  tests;
- `pre-push` runs the same checks plus the macOS integration suite.

Enable them without reinstalling the app:

```sh
bash scripts/install_git_hooks.sh
```

Run either check set directly:

```sh
bash scripts/run_checks.sh quick   # macOS-oriented (includes plutil / launchd)
bash scripts/run_checks.sh full
pwsh scripts/run_checks.ps1 quick
bash scripts/run_checks_linux.sh quick
```

A failed check blocks the commit or push. Git’s standard `--no-verify` option
remains available for emergencies, but CI still runs the full suite.

## Troubleshooting

### All platforms

- **Claude CLI not found:** run `which claude` (or `Get-Command claude` on Windows), set `CLAUDE_BIN=...` in private `config.env`, then run a [manual scan](#daily-use-by-os).
- **Gmail scan fails:** confirm Claude works interactively and Gmail MCP tools are connected. Check `logs/scan.log`.
- **Gmail scan fails only on a schedule:** background PATH is limited — set `CLAUDE_BIN` to an absolute path in `config.env`, then reload schedulers (`python3 bin/scheduler.py sync` or re-run your OS installer).
- **No ntfy push:** verify `NTFY_TOPIC` in private config. Treat the topic as a secret.
- **Dashboard is stale:** run `python3 bin/merge_interviews.py`.
- **Settings did not apply:** confirm menu/tray app is running; retry Settings; run `python3 bin/scheduler.py sync`.
- **Moved clone:** re-run the [installer for your OS](#reinstall-and-uninstall).
- **Overlapping scans:** only one scan at a time; a second start exits while `scan.lock/` exists.

### macOS

- **No scheduled run:** `launchctl print "gui/$(id -u)/com.interview-tracker.scheduler"`. Calendar triggers may not run while the Mac is asleep.
- **No notification:** check `logs/notifier.log`, notification permissions, Focus; install `terminal-notifier` if AppleScript alerts are unreliable.
- **Menu app does not start:** `logs/menubar.err.log`, confirm `venv/bin/python3`, rerun `bash install.sh`.

### Windows

- **Tray missing:** check Task Scheduler `InterviewTracker\Tray`; run `.\venv\Scripts\python.exe .\bin\tray_app.py` manually; ensure `requirements-windows.txt` installed.
- **Scheduled scan missing:** `schtasks /Query /TN InterviewTracker\GmailScan`; re-run `install.ps1` after changing scan times in Settings.
- **Toast notifications:** requires `win10toast` (installed by `install.ps1`).

### Linux

- **Tray missing:** `systemctl --user status interview-tracker-tray.service`; graphical session required; on Wayland install AppIndicator/libappindicator packages as needed for pystray.
- **No desktop notification:** install `libnotify-bin` (`notify-send`); check `logs/notifier.log`.
- **Timer not firing:** `systemctl --user list-timers`; consider `loginctl enable-linger "$USER"` for scans when logged out.
- **systemctl --user fails:** ensure a user systemd session is active (log in locally, not only SSH without lingering).

## Distribution status

This architecture is **not** an app-store product on any OS. It depends on the
Claude CLI, Python virtual environments, private files outside sandboxes, and
Gmail access through Claude MCP tooling.

- **macOS:** shell scripts, launchd agents, external venv, non-sandboxed `.app` wrapper.
- **Windows:** Task Scheduler, system tray, user `%LOCALAPPDATA%` data.
- **Linux:** systemd user units, system tray, XDG data paths.

An App Store / Microsoft Store / Flatpak-style product would be a separate phase:
signed sandboxed app, in-app scheduling, secure credential storage, and direct
Gmail OAuth rather than Claude MCP.
