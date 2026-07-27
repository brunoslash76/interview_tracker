#!/bin/bash
# Run Playwright full-stack E2E against the hermetic test server (Chromium by default).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BROWSER="${1:-chromium}"

cd "${ROOT}"

if [ -x "${ROOT}/venv/bin/python3" ]; then
  PYTHON="${ROOT}/venv/bin/python3"
else
  PYTHON="$(command -v python3)"
fi

if ! "${PYTHON}" -c "import uvicorn" >/dev/null 2>&1; then
  echo "Installing Python dependencies for E2E server…"
  "${PYTHON}" -m pip install -r requirements-dev.txt
fi

if [ ! -d "${ROOT}/frontend/node_modules" ]; then
  (cd frontend && npm ci)
fi

echo "Building frontend for E2E…"
(cd frontend && npm run build)

echo "Installing Playwright (${BROWSER})…"
(cd frontend && npx playwright install --with-deps "${BROWSER}")

echo "Running Playwright E2E (${BROWSER})…"
(cd frontend && npm run test:e2e -- --project="${BROWSER}")
