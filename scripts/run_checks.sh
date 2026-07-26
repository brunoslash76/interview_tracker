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

if [ -x "${ROOT}/venv/bin/python3" ]; then
  PYTHON="${ROOT}/venv/bin/python3"
else
  PYTHON="$(command -v python3)"
fi

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

if [ "${MODE}" = "quick" ]; then
  echo "Running unit and component tests…"
  "${PYTHON}" -m unittest discover -s tests -p 'test_*_unit.py' -v
else
  if ! "${PYTHON}" -m coverage --version >/dev/null 2>&1; then
    echo "ERROR: coverage.py is required for full pre-push checks." >&2
    echo "Run: ${PYTHON} -m pip install -r requirements-dev.txt" >&2
    exit 1
  fi

  echo "Running unit and component tests with coverage…"
  "${PYTHON}" -m coverage erase
  "${PYTHON}" -m coverage run -m unittest discover -s tests -p 'test_*_unit.py' -v

  echo "Running integration tests with coverage…"
  "${PYTHON}" -m coverage run --append \
    -m unittest discover -s tests -p 'test_integration_*.py' -v

  echo "Enforcing Python coverage threshold…"
  "${PYTHON}" -m coverage report --fail-under=80
  "${PYTHON}" -m coverage xml
  "${PYTHON}" -m coverage json -o coverage.json
  "${PYTHON}" scripts/generate_coverage_badge.py coverage.json coverage.svg

  if ! git diff --quiet HEAD -- coverage.svg; then
    echo "ERROR: coverage.svg changed. Commit the refreshed README badge." >&2
    exit 1
  fi
fi

echo "All ${MODE} checks passed."
