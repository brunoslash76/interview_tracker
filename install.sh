#!/bin/bash
# Interview Tracker — unified installer (merged project).
# Run once from inside the project folder:
#   macOS:    bash install.sh
#   Linux:    bash install.sh   → delegates to install-linux.sh
#   Windows (Git Bash):   bash install.sh  → delegates to install.ps1
#   Windows (native):     powershell -ExecutionPolicy Bypass -File install.ps1
#
# Installs three launchd agents (scheduler + notifier + menu bar), builds the
# menu-bar app's Python venv, and migrates off any earlier interview-tracker
# agents. Publishable plist templates are rendered for this clone at install.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "$(uname -s)" in
  Darwin) ;;
  Linux)
    echo "Detected Linux — running install-linux.sh…"
    exec bash "${ROOT}/install-linux.sh"
    ;;
  MINGW*|MSYS*|CYGWIN*)
    echo "Detected Windows shell environment — running install.ps1…"
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${ROOT}/install.ps1"
    exit $?
    ;;
  *)
    echo "ERROR: Unsupported platform for install.sh."
    echo "  macOS:   bash install.sh"
    echo "  Linux:   bash install-linux.sh"
    echo "  Windows: powershell -ExecutionPolicy Bypass -File install.ps1"
    exit 1
    ;;
esac

DATA_DIR="${INTERVIEW_TRACKER_DATA_DIR:-${HOME}/Library/Application Support/InterviewTracker}"
AGENT_DIR="${HOME}/Library/LaunchAgents"
PLISTS=(com.interview-tracker.notifier com.interview-tracker.menubar)
OLD_LABELS=(com.interview-tracker.scheduler com.interview-tracker.notifier com.interview-tracker.menubar)
PYTHON="/usr/bin/python3"

echo "Installing Interview Tracker from ${ROOT}"
echo "Private data directory: ${DATA_DIR}"

check_python_prerequisites() {
  local missing=0
  PREREQ_ISSUES=()

  if [ ! -x "${PYTHON}" ]; then
    PREREQ_ISSUES+=("${PYTHON} is not installed or not executable")
    missing=1
    return "${missing}"
  fi

  if ! "${PYTHON}" -c "import venv" 2>/dev/null; then
    PREREQ_ISSUES+=("Python venv module is not available (try: xcode-select --install)")
    missing=1
  fi

  if ! "${PYTHON}" -m pip --version >/dev/null 2>&1; then
    PREREQ_ISSUES+=("Python pip is not available for ${PYTHON}")
    missing=1
  fi

  return "${missing}"
}

project_venv_ready() {
  [ -x "${ROOT}/venv/bin/python3" ] \
    && "${ROOT}/venv/bin/python3" -m pip --version >/dev/null 2>&1
}

install_python_dependencies() {
  echo "Creating runtime folders…"
  mkdir -p "${DATA_DIR}/logs" "${AGENT_DIR}"

  if [ ! -x "${PYTHON}" ]; then
    echo "ERROR: ${PYTHON} is required but was not found."
    echo "Install Xcode Command Line Tools or a system Python 3, then retry."
    exit 1
  fi

  if ! "${PYTHON}" -m pip --version >/dev/null 2>&1; then
    echo "Bootstrapping pip with ensurepip…"
    if ! "${PYTHON}" -m ensurepip --upgrade --default-pip >/dev/null 2>&1; then
      echo "ERROR: pip is still unavailable after ensurepip."
      exit 1
    fi
  fi

  if ! "${PYTHON}" -c "import venv" 2>/dev/null; then
    echo "ERROR: the Python venv module is still unavailable."
    echo "On macOS, run: xcode-select --install"
    exit 1
  fi

  if [ ! -d "${ROOT}/venv" ]; then
    echo "Creating project virtual environment at ${ROOT}/venv …"
    "${PYTHON}" -m venv "${ROOT}/venv"
  elif [ ! -x "${ROOT}/venv/bin/python3" ]; then
    echo "Recreating incomplete project virtual environment…"
    rm -rf "${ROOT}/venv"
    "${PYTHON}" -m venv "${ROOT}/venv"
  fi

  echo "Installing menu-bar dependencies (pip, rumps, pyobjc)…"
  "${ROOT}/venv/bin/python3" -m pip install --quiet --upgrade pip
  "${ROOT}/venv/bin/python3" -m pip install --quiet rumps pyobjc
  "${ROOT}/venv/bin/python3" -m pip install --quiet -r "${ROOT}/requirements-dev.txt"
  echo "Python dependencies installed."
}

echo "Checking Python prerequisites…"
needs_setup=0
if ! check_python_prerequisites; then
  needs_setup=1
fi
if ! project_venv_ready; then
  needs_setup=1
  PREREQ_ISSUES+=("Project venv is missing or incomplete (${ROOT}/venv)")
fi

if [ "${needs_setup}" -eq 1 ]; then
  echo "Some dependencies are missing:"
  for issue in "${PREREQ_ISSUES[@]}"; do
    echo "  - ${issue}"
  done
  read -r -p "Create required folders and install Python dependencies? [y/N] " ok
  if [ "${ok}" != "y" ]; then
    echo "Installation cancelled."
    exit 1
  fi
  install_python_dependencies
else
  echo "Python prerequisites OK."
  mkdir -p "${DATA_DIR}/logs" "${AGENT_DIR}"
fi

if ! "${ROOT}/venv/bin/python3" -m coverage --version >/dev/null 2>&1; then
  echo "Installing development coverage tooling…"
  "${ROOT}/venv/bin/python3" -m pip install --quiet -r "${ROOT}/requirements-dev.txt"
fi

# --- permissions + folders --------------------------------------------------
chmod +x "${ROOT}/bin/scan_gmail.sh" "${ROOT}/bin/scan_gmail.py" "${ROOT}/bin/macos_notifier.sh" \
         "${ROOT}/bin/notifier.py" "${ROOT}/bin/merge_interviews.py" "${ROOT}/bin/menubar_app.py" \
         "${ROOT}/bin/migrate_json_to_sqlite.py" "${ROOT}/bin/scheduler.py" \
         "${ROOT}/bin/local_server.py" \
         "${ROOT}/scripts/install_git_hooks.sh" "${ROOT}/scripts/run_checks.sh" \
         "${ROOT}/scripts/generate_coverage_badge.py" \
         "${ROOT}/.githooks/pre-commit" "${ROOT}/.githooks/pre-push" \
         "${ROOT}/InterviewTracker.app/Contents/MacOS/InterviewTracker"

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

# --- migrate off any earlier agents (email-reader + old .interview_tracker) --
for old in "${OLD_LABELS[@]}"; do
    if launchctl list 2>/dev/null | grep -q "$old"; then
        echo "unloading previous agent: $old"
        launchctl bootout "gui/$(id -u)/${old}" 2>/dev/null || true
    fi
done
# --- install the three agents -----------------------------------------------
for label in "${PLISTS[@]}"; do
    template="${ROOT}/launchd/${label}.plist"
    installed="${AGENT_DIR}/${label}.plist"

    if ! plutil -lint "${template}" >/dev/null; then
        echo "ERROR: source template ${label}.plist is malformed. Aborting."
        exit 1
    fi

    /usr/bin/python3 - "${template}" "${installed}" "${ROOT}" "${HOME}" "${DATA_DIR}" <<'PY'
import sys
from pathlib import Path
from xml.sax.saxutils import escape

source, destination, root, home, data_dir = sys.argv[1:]
text = Path(source).read_text(encoding="utf-8")
values = {
    "__ROOT__": root,
    "__HOME__": home,
    "__DATA_DIR__": data_dir,
}
for placeholder, value in values.items():
    text = text.replace(
        placeholder,
        escape(value, {'"': "&quot;", "'": "&apos;"}),
    )
unresolved = [placeholder for placeholder in values if placeholder in text]
if unresolved:
    raise SystemExit(f"unresolved plist placeholders: {', '.join(unresolved)}")
Path(destination).write_text(text, encoding="utf-8")
PY
    chmod 644 "${AGENT_DIR}/${label}.plist"
    if ! plutil -lint "${installed}" >/dev/null; then
        echo "ERROR: ${label}.plist is malformed. Aborting."
        exit 1
    fi
    launchctl bootstrap "gui/$(id -u)" "${installed}" 2>/dev/null \
        || launchctl load "${installed}" 2>/dev/null || true
    if ! launchctl print "gui/$(id -u)/${label}" >/dev/null 2>&1; then
        launchctl bootstrap "gui/$(id -u)" "${installed}" 2>/dev/null || true
    fi
    if launchctl print "gui/$(id -u)/${label}" >/dev/null 2>&1; then
        echo "loaded ${label}"
    else
        echo "WARNING: could not load ${label}; the rendered plist remains installed."
    fi
done

echo "Syncing Gmail scan scheduler from SQLite…"
INTERVIEW_TRACKER_DATA_DIR="${DATA_DIR}" \
    "${ROOT}/venv/bin/python3" "${ROOT}/bin/scheduler.py" sync \
    --root "${ROOT}" --home "${HOME}" --data-dir "${DATA_DIR}" \
    --db "${DATA_DIR}/interview_tracker.sqlite3"

echo "Configuring repository Git hooks…"
"${ROOT}/scripts/install_git_hooks.sh"

echo
echo "Installed. Configure scan times in Settings (menu bar → Settings)."
echo
echo "  Scan now:      bash ${ROOT}/bin/scan_gmail.sh"
echo "  Open dashboard: open InterviewTracker.app → Open Full Dashboard"
echo "  Launch menubar:open ${ROOT}/InterviewTracker.app"
echo "  Status:        launchctl list | grep interview-tracker"
echo "  Logs:          tail -f ${DATA_DIR}/logs/scan.log"
echo
echo "  If the Gmail scan can't find the CLI, set CLAUDE_BIN in ${DATA_DIR}/config.env."
echo "  For reliable notifications: brew install terminal-notifier"
