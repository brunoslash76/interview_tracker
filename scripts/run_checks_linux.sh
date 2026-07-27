#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-quick}"

case "${MODE}" in
  quick|full|commit) ;;
  *)
    echo "Usage: $0 [quick|commit|full]" >&2
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

if [ ! -d "${ROOT}/frontend/node_modules" ]; then
  (cd frontend && npm ci)
fi
echo "Testing and building React frontend…"
if [ "${MODE}" = "full" ]; then
  (cd frontend && npm run test:coverage && npm run build)
  "${PYTHON}" scripts/generate_coverage_badge.py \
    frontend/coverage/coverage-summary.json frontend-coverage.svg --label frontend
  if ! git diff --quiet HEAD -- frontend-coverage.svg; then
    echo "ERROR: frontend-coverage.svg changed. Commit the refreshed README badge." >&2
    exit 1
  fi
  echo "Installing Playwright (chromium) for Storybook tests…"
  (cd frontend && npx playwright install --with-deps chromium)
  (cd frontend && npm run build-storybook)
  (cd frontend && npm run test:storybook:static)
else
  (cd frontend && npm test && npm run build)
fi

if [ "${MODE}" = "commit" ]; then
  bash "${ROOT}/scripts/run_frontend_e2e.sh" chromium
fi

if [ "${MODE}" = "quick" ] || [ "${MODE}" = "commit" ]; then
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
