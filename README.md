# Interview Tracker

[![Tests](https://github.com/brunoslash76/interview_tracker/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/brunoslash76/interview_tracker/actions/workflows/tests.yml)

Interview Tracker is a local macOS automation that scans Gmail for job-interview
threads, merges structured results into a private SQLite database, renders an
HTML dashboard, and sends change-aware notifications. A lightweight Python
menu-bar app shows current counts and can start a scan.

The repository contains code and portable templates only. User records,
configuration, generated pages, logs, and backups live outside the clone.

## Current architecture

1. `launchd` runs `bin/scan_gmail.sh` on the daily scan times configured in
   **Settings** (default 09:00 and 20:00 local system time), or the script can
   be started manually.
2. The script runs the Claude CLI headlessly with only the Gmail thread-search
   and thread-read MCP tools allowed. It scans with a five-day overlap from the
   last successful scan; the first scan looks back 120 days.
3. Claude returns schema-constrained JSON to a temporary private file.
   `bin/merge_interviews.py` merges it transactionally into SQLite and regenerates
   the private dashboard.
4. The notifier LaunchAgent watches the SQLite file. It reads the latest scan
   summary and compares its data hash with `.last_notified_hash`; unchanged data
   stays silent. Changed data produces a macOS notification and, when configured,
   an optional ntfy push.
5. The login LaunchAgent opens `InterviewTracker.app`, a small shell wrapper
   around the rumps/PyObjC menu app. It starts a loopback-only local web server,
   reads SQLite, refreshes its menu when the database changes, opens the
   dashboard and settings pages, and exposes **Refresh Now**.

SQLite uses rollback-journal mode so committed writes update the database file
observed by `launchd`. The menu app's 60-second local file check does not scan
Gmail.

## Prerequisites

- macOS 11 or later
- `/usr/bin/python3`, including `venv` and `pip`
- **Claude CLI** with Gmail access configured (see [Set up Claude](#set-up-claude-required-before-gmail-scans) below)
- Network access during installation for `rumps` and `pyobjc`
- Optional: `brew install terminal-notifier` for more reliable Mac alerts
- Optional: the ntfy app and a private topic for phone/watch pushes

## Set up Claude (required before Gmail scans)

Interview Tracker does **not** call the Gmail API itself. Every scan runs the
**Claude CLI** headlessly and uses Claude’s Gmail MCP tools to search threads and
read message content. Complete this setup **before** you rely on scheduled scans
or **Refresh Now**; you can still run `bash install.sh` to install agents and
the menu-bar app, but scans will fail until Claude is ready.

### 1. Install the Claude CLI

Install Anthropic’s Claude CLI on your Mac using the method described in the
current [Claude Code documentation](https://docs.anthropic.com/en/docs/claude-code/overview)
(for example the official installer or your package manager).

Confirm the binary is on your PATH:

```sh
which claude
claude --version
```

If `which claude` prints a path outside launchd’s default PATH (often something
under `~/.local/bin` or Homebrew), you will set `CLAUDE_BIN` in the private
`config.env` after installation (step 5).

### 2. Sign in to Claude

Log in from the terminal so non-interactive scans can run:

```sh
claude
```

Follow the prompts until the CLI is authenticated. Use the same flow recommended
in Anthropic’s docs for your CLI version (browser login, API key, or subscription,
depending on how your install is configured).

### 3. Connect Gmail to Claude

The scan script only allows these tools (see `bin/scan_gmail.sh`):

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

After you install Interview Tracker, run one manual scan:

```sh
cd email-reader
bash bin/scan_gmail.sh
tail -20 "$HOME/Library/Application Support/InterviewTracker/logs/scan.log"
```

You should see a completed scan, not `claude CLI not found` or MCP/tool errors.

### 5. Point launchd at the Claude binary (if needed)

Background jobs use a limited PATH. If scans work in Terminal but not on a
schedule, set the full path in the **private** config file:

```sh
open -e "$HOME/Library/Application Support/InterviewTracker/config.env"
```

Example (use your path from `which claude`):

```sh
CLAUDE_BIN=/Users/you/.local/bin/claude
```

Save the file, then test again with `bash bin/scan_gmail.sh`.

## Install

```sh
git clone <repository-url> email-reader
cd email-reader
bash install.sh
```

The installer:

- creates `~/Library/Application Support/InterviewTracker`;
- copies `config.env.example` to the private `config.env` if none exists;
- initializes SQLite and renders the initial dashboard;
- performs any legacy JSON migration described below;
- builds the repository-local `venv/` for the menu app;
- renders the portable plist templates into `~/Library/LaunchAgents`; and
- syncs the Gmail scheduler LaunchAgent from SQLite; and
- loads the scheduler, notifier, and menu-bar LaunchAgents.

If you have not completed [Set up Claude](#set-up-claude-required-before-gmail-scans),
do that before expecting Gmail scans to work.

Edit the private config after installation:

```sh
open -e "$HOME/Library/Application Support/InterviewTracker/config.env"
```

Set `CLAUDE_BIN` to the executable reported by `which claude` if launchd cannot
find it. Set `NTFY_TOPIC` only if desired. Do not put secrets or private topic
names in the repository.

## Private runtime files

The default runtime location is:

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
manual or custom deployments; installed LaunchAgents retain the location
rendered at install time.

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

Open **Interview Tracker → Settings** from the menu bar, or use **Settings** in
the dashboard header when viewing it through the local server.

From Settings you can:

- add or remove up to five daily scan times using time inputs;
- save and apply the schedule, which updates SQLite and reloads the single
  `com.interview-tracker.scheduler` LaunchAgent; and
- set an optional email address used to restrict Gmail searches to messages
  involving that address.

Important limitations:

- scan times use your Mac's local time zone and follow the usual launchd
  calendar behavior (they do not queue while the Mac is asleep);
- removing all scan times disables automatic scans but keeps manual **Refresh
  Now** working;
- the email field is a Gmail search filter hint (`to:` / `from:` involvement),
  not an account switch — authenticate the correct Google account in the
  Claude CLI yourself;
- Claude's Gmail MCP tools enforce this filter only as well as the model follows
  the scan prompt.

The settings UI is served only on `127.0.0.1` by the menu-bar app. Writes require
a SameSite CSRF cookie and a matching request origin. If the menu-bar app is not
running, open the static private `dashboard.html` fallback instead (Settings
links will not work there).

When the loopback server is running, the dashboard header includes **Scan Gmail
now**. It starts the same `bin/scan_gmail.sh` pipeline as **Refresh Now**, shows
a progress modal with live phase updates, and refreshes the table in place when
the scan finishes.

## Manual operation

Run these commands from the clone:

```sh
bash bin/scan_gmail.sh
open InterviewTracker.app

python3 bin/database.py settings-json
python3 bin/database.py scan-config-json
python3 bin/scheduler.py sync --no-load
python3 bin/database.py records-json
python3 bin/database.py summary-json
python3 bin/database.py last-scan-date
python3 bin/merge_interviews.py       # re-render without scanning Gmail

launchctl list | grep interview-tracker
launchctl kickstart -k "gui/$(id -u)/com.interview-tracker.scheduler"
tail -f "$HOME/Library/Application Support/InterviewTracker/logs/scan.log"
```

Pause or resume all agents:

```sh
for name in scheduler notifier menubar; do
  launchctl bootout "gui/$(id -u)/com.interview-tracker.$name" 2>/dev/null || true
done

for name in scheduler notifier menubar; do
  launchctl bootstrap "gui/$(id -u)" \
    "$HOME/Library/LaunchAgents/com.interview-tracker.$name.plist"
done
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

## Portable launchd templates

The checked-in `launchd/*.plist` files use `__ROOT__`, `__HOME__`, and
`__DATA_DIR__` placeholders; they contain no machine-specific paths.
`install.sh` XML-escapes the current values, writes the rendered plists under
`~/Library/LaunchAgents`, validates them with `plutil`, and loads them. Re-run
the installer after moving the clone or changing the runtime directory.

## Source tree and privacy

- `bin/` contains SQLite, scan, merge, notifier, migration, and menu code.
- `launchd/` contains portable LaunchAgent templates.
- `InterviewTracker.app/` is a minimal menu-bar wrapper, not a self-contained
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

The suite uses **stdlib `unittest` only** (no pytest). Tests never call live
Claude/Gmail, ntfy, or your private
`~/Library/Application Support/InterviewTracker` data. Integration tests set
temporary `HOME` and `INTERVIEW_TRACKER_DATA_DIR` and use fixture fakes under
[`tests/fixtures/`](/Users/bruno/Automations/email-reader/tests/fixtures/).

```sh
# All tests
python3 -m unittest discover -s tests -v

# Unit tests only
python3 -m unittest discover -s tests -p 'test_*_unit.py' -v

# Integration tests (macOS; shell + settings end-to-end)
python3 -m unittest discover -s tests -p 'test_integration_*.py' -v
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

CI runs the same commands on **`macos-latest`** via
[`.github/workflows/tests.yml`](/Users/bruno/Automations/email-reader/.github/workflows/tests.yml).
The badge at the top of this README reflects that workflow on the `main` branch
(passes when unit and integration tests succeed on GitHub’s macOS runners).

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
bash scripts/run_checks.sh quick
bash scripts/run_checks.sh full
```

A failed check blocks the commit or push. Git’s standard `--no-verify` option
remains available for emergencies, but CI still runs the full suite.

## Troubleshooting

- **Claude CLI not found:** run `which claude`, put that path in the private
  `config.env` as `CLAUDE_BIN=...`, then run `bash bin/scan_gmail.sh`.
- **Gmail scan fails:** confirm the Claude CLI works interactively and that the
  Gmail connector exposes the two MCP tools named in `bin/scan_gmail.sh`. Check
  `logs/scan.log` and `logs/scheduler.err.log`.
- **No scheduled run:** inspect
  `launchctl print "gui/$(id -u)/com.interview-tracker.scheduler"`. Calendar
  triggers use the Mac's local time and may not run while the Mac is asleep.
- **No notification:** unchanged hashes intentionally stay silent. Check
  `logs/notifier.log`, macOS notification permissions, Focus settings, and
  install `terminal-notifier` if AppleScript alerts are unreliable.
- **No ntfy push:** verify `NTFY_TOPIC` in the private config and the device's
  subscription. Treat the topic name as a secret.
- **Menu app does not start:** inspect `logs/menubar.err.log`, confirm
  `venv/bin/python3` exists, and rerun `bash install.sh`.
- **Dashboard is stale:** run `python3 bin/merge_interviews.py`; if that fails,
  check database permissions and available disk space.
- **Settings did not apply:** confirm the menu-bar app is running, retry from
  Settings, then inspect `logs/scheduler.err.log`. You can also run
  `python3 bin/scheduler.py sync`.
- **Moved clone:** rerun `bash install.sh` so the installed plists contain the
  new path.
- **Overlapping scans:** only one Gmail scan runs at a time; a second trigger
  exits cleanly while `scan.lock/` exists.

## Distribution status

This architecture is **not Mac App Store-ready**. It depends on the Claude CLI,
shell scripts, launchd agents, an external Python virtual environment, private
files outside an app sandbox, and Gmail access through Claude MCP tooling.

An App Store product would be a separate phase: a native, signed and sandboxed
application with appropriate entitlements, in-app scheduling/background
behavior, secure credential storage, and its own Gmail OAuth consent and token
flow. The current `.app` wrapper should not be presented as that product.
