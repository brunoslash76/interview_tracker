#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! git -C "${ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Skipping Git hooks: ${ROOT} is not a Git working tree."
  exit 0
fi

git -C "${ROOT}" config --local core.hooksPath .githooks
echo "Git hooks enabled from ${ROOT}/.githooks"
