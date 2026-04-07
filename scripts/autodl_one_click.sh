#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"${PROJECT_ROOT}/scripts/autodl_setup.sh"
"${PROJECT_ROOT}/scripts/autodl_run.sh" "$@"
