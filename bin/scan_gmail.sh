#!/bin/bash
# Thin macOS wrapper — canonical implementation is bin/scan_gmail.py
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${ROOT}/venv/bin/python3"
if [ ! -x "${PYTHON}" ]; then
  PYTHON="/usr/bin/python3"
fi
exec "${PYTHON}" "${ROOT}/bin/scan_gmail.py" "$@"
