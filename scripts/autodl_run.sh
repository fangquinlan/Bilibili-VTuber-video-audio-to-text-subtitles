#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-vtuber_subtitles}"
SERIES_URL="${SERIES_URL:-https://space.bilibili.com/1878154667/lists/2004017?type=series}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${PROJECT_ROOT}/workspace/bilibili_series_2004017}"
MODEL_PROVIDER="${MODEL_PROVIDER:-auto}"
DEVICE="${DEVICE:-auto}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
INPUT_FILE="${INPUT_FILE:-${PROJECT_ROOT}/input.txt}"
AUDIO_QUALITY="${AUDIO_QUALITY:-low}"
ASR_CHUNK_MINUTES="${ASR_CHUNK_MINUTES:-20}"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda was not found in PATH. Run scripts/autodl_setup.sh first." >&2
  exit 1
fi

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV_NAME}"

args=(
  python -m vtuber_subtitles.cli run-series
  --series-url "${SERIES_URL}"
  --input-file "${INPUT_FILE}"
  --output-root "${OUTPUT_ROOT}"
  --model-provider "${MODEL_PROVIDER}"
  --device "${DEVICE}"
  --audio-quality "${AUDIO_QUALITY}"
  --asr-chunk-minutes "${ASR_CHUNK_MINUTES}"
  --log-level "${LOG_LEVEL}"
)

"${args[@]}" "$@"
