#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-vtuber_subtitles}"
SERIES_URL="${SERIES_URL:-https://space.bilibili.com/1878154667/lists/2004017?type=series}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${PROJECT_ROOT}/workspace/bilibili_series_2004017}"
MODEL_PROVIDER="${MODEL_PROVIDER:-auto}"
DEVICE="${DEVICE:-auto}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda was not found in PATH. Run scripts/autodl_setup.sh first." >&2
  exit 1
fi

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV_NAME}"

python -m vtuber_subtitles.cli run-series \
  --series-url "${SERIES_URL}" \
  --output-root "${OUTPUT_ROOT}" \
  --model-provider "${MODEL_PROVIDER}" \
  --device "${DEVICE}" \
  --log-level "${LOG_LEVEL}" \
  "$@"
