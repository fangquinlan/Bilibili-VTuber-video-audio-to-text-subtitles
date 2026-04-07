#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN=python
else
  echo "python3 or python was not found in PATH." >&2
  exit 1
fi

exec "${PYTHON_BIN}" "${PROJECT_ROOT}/scripts/autodl_one_click.py" "$@"
