#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-quick}"

case "${MODE}" in
  quick|full) ;;
  *)
    echo "Usage: $0 [quick|full]" >&2
    exit 2
    ;;
esac

cd "${ROOT}"

echo "Validating shell scripts…"
bash -n install.sh
bash -n bin/scan_gmail.sh
bash -n bin/macos_notifier.sh
bash -n InterviewTracker.app/Contents/MacOS/InterviewTracker
bash -n scripts/run_checks.sh
bash -n scripts/install_git_hooks.sh
bash -n .githooks/pre-commit
bash -n .githooks/pre-push

echo "Validating launchd templates…"
plutil -lint launchd/*.plist InterviewTracker.app/Contents/Info.plist >/dev/null

if ! command -v node >/dev/null 2>&1; then
  echo "ERROR: Node.js is required for dashboard component tests." >&2
  echo "Install Node.js, then retry the commit or push." >&2
  exit 1
fi

echo "Validating dashboard component harness…"
node --check tests/dashboard_component_harness.js

echo "Running unit and component tests…"
python3 -m unittest discover -s tests -p 'test_*_unit.py' -v

if [ "${MODE}" = "full" ]; then
  echo "Running integration tests…"
  python3 -m unittest discover -s tests -p 'test_integration_*.py' -v
fi

echo "All ${MODE} checks passed."
