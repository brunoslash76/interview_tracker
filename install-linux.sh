#!/bin/bash
# Interview Tracker — Linux installer (systemd user units).
# Run from the project folder:  bash install-linux.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(uname -s)" != "Linux" ]; then
  echo "ERROR: install-linux.sh requires Linux."
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "ERROR: systemd (systemctl) is required."
  exit 1
fi

DATA_DIR="${INTERVIEW_TRACKER_DATA_DIR:-${XDG_DATA_HOME:-${HOME}/.local/share}/InterviewTracker}"
PYTHON="$(command -v python3)"

echo "Installing Interview Tracker from ${ROOT}"
echo "Private data directory: ${DATA_DIR}"

if [ -z "${PYTHON}" ]; then
  echo "ERROR: python3 is required but was not found."
  exit 1
fi

if [ ! -d "${ROOT}/venv" ] || [ ! -x "${ROOT}/venv/bin/python3" ]; then
  echo "Creating project virtual environment…"
  "${PYTHON}" -m venv "${ROOT}/venv"
fi

echo "Installing Linux runtime dependencies…"
"${ROOT}/venv/bin/python3" -m pip install --quiet --upgrade pip
"${ROOT}/venv/bin/python3" -m pip install --quiet -r "${ROOT}/requirements-linux.txt"
"${ROOT}/venv/bin/python3" -m pip install --quiet -r "${ROOT}/requirements-dev.txt"

mkdir -p "${DATA_DIR}/logs"

chmod +x "${ROOT}/bin/scan_gmail.py" "${ROOT}/bin/notifier.py" "${ROOT}/bin/tray_app.py" \
         "${ROOT}/bin/merge_interviews.py" "${ROOT}/bin/scheduler.py" \
         "${ROOT}/scripts/install_git_hooks.sh"

echo "Initializing private database…"
INTERVIEW_TRACKER_DATA_DIR="${DATA_DIR}" \
  "${ROOT}/venv/bin/python3" "${ROOT}/bin/database.py" \
  --db "${DATA_DIR}/interview_tracker.sqlite3" init >/dev/null

echo "Checking for legacy private data…"
INTERVIEW_TRACKER_DATA_DIR="${DATA_DIR}" \
  "${ROOT}/venv/bin/python3" "${ROOT}/bin/migrate_json_to_sqlite.py"

if [ -f "${ROOT}/config.env.example" ] && [ ! -f "${DATA_DIR}/config.env" ]; then
  cp "${ROOT}/config.env.example" "${DATA_DIR}/config.env"
  chmod 600 "${DATA_DIR}/config.env"
  echo "Created private config: ${DATA_DIR}/config.env"
fi

INTERVIEW_TRACKER_DATA_DIR="${DATA_DIR}" \
  "${ROOT}/venv/bin/python3" "${ROOT}/bin/merge_interviews.py" >/dev/null

echo "Syncing Gmail scan scheduler from SQLite…"
INTERVIEW_TRACKER_DATA_DIR="${DATA_DIR}" \
  "${ROOT}/venv/bin/python3" "${ROOT}/bin/scheduler.py" sync \
  --root "${ROOT}" --home "${HOME}" --data-dir "${DATA_DIR}" \
  --db "${DATA_DIR}/interview_tracker.sqlite3"

echo "Installing notifier and tray systemd user units…"
INTERVIEW_TRACKER_DATA_DIR="${DATA_DIR}" \
  "${ROOT}/venv/bin/python3" -c "
import scheduler_systemd as s
from pathlib import Path
root = Path('${ROOT}')
home = Path('${HOME}')
data = Path('${DATA_DIR}')
s.sync_notifier_units(root, home, data, load_agent=True)
s.sync_tray_service(root, home, data, load_agent=True)
"

echo "Configuring repository Git hooks…"
"${ROOT}/scripts/install_git_hooks.sh"

echo
echo "Installed. Configure scan times in Settings (tray icon → Settings)."
echo
echo "  Scan now:       ${ROOT}/venv/bin/python3 ${ROOT}/bin/scan_gmail.py"
echo "  Open dashboard: tray icon → Open Full Dashboard"
echo "  Unit status:    systemctl --user status interview-tracker-scan.timer"
echo "  Tray status:    systemctl --user status interview-tracker-tray.service"
echo "  Logs:           tail -f ${DATA_DIR}/logs/scan.log"
echo "  Journal:        journalctl --user -u interview-tracker-tray.service -f"
echo
echo "  Optional (scans after logout): loginctl enable-linger \"\${USER}\""
echo "  If the Gmail scan can't find the CLI, set CLAUDE_BIN in ${DATA_DIR}/config.env."
echo "  Desktop notifications need notify-send (libnotify-bin on Debian/Ubuntu)."
