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

echo "Validating dashboard component harness…"
node --check tests/dashboard_component_harness.js

if [ "${MODE}" = "quick" ]; then
  echo "Running unit and component tests…"
  "${PYTHON}" -m unittest discover -s tests -p 'test_*_unit.py' -v
else
  if ! "${PYTHON}" -m coverage --version >/dev/null 2>&1; then
    echo "ERROR: coverage.py is required for full checks." >&2
    exit 1
  fi
  "${PYTHON}" -m coverage erase
  "${PYTHON}" -m coverage run -m unittest discover -s tests -p 'test_*_unit.py' -v
  "${PYTHON}" -m coverage run --append -m unittest discover -s tests -p 'test_integration_*.py' -v
  "${PYTHON}" -m coverage report --fail-under=80
fi

echo "All ${MODE} checks passed."
