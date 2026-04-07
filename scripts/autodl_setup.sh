#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-vtuber_subtitles}"
PYTHON_VERSION="${PYTHON_VERSION:-3.10}"
FIRERED_COMMIT="${FIRERED_COMMIT:-466c9bb718240132f42ec1b9df14cc6aecae587d}"

apt_install_if_missing() {
  local binary="$1"
  local package_name="$2"
  if command -v "$binary" >/dev/null 2>&1; then
    return 0
  fi

  local -a apt_runner
  if [[ "${EUID}" -eq 0 ]]; then
    apt_runner=(apt-get)
  elif command -v sudo >/dev/null 2>&1; then
    apt_runner=(sudo apt-get)
  else
    echo "Need root or sudo to install ${package_name}." >&2
    exit 1
  fi
  "${apt_runner[@]}" update
  "${apt_runner[@]}" install -y "$package_name"
}

require_conda() {
  if ! command -v conda >/dev/null 2>&1; then
    echo "conda was not found in PATH. Please open your AutoDL conda environment first." >&2
    exit 1
  fi
}

apt_install_if_missing git git
apt_install_if_missing ffmpeg ffmpeg
require_conda

source "$(conda info --base)/etc/profile.d/conda.sh"

if ! conda env list | awk '{print $1}' | grep -qx "${CONDA_ENV_NAME}"; then
  conda create -y -n "${CONDA_ENV_NAME}" "python=${PYTHON_VERSION}"
fi

conda activate "${CONDA_ENV_NAME}"

python -m pip install --upgrade pip setuptools wheel
python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
python -m pip install -r "${PROJECT_ROOT}/requirements.txt"
python -m pip install --no-deps -e "${PROJECT_ROOT}"
python -m pip install --no-deps "git+https://github.com/FireRedTeam/FireRedASR2S.git@${FIRERED_COMMIT}"

python - <<'PY'
import torch
print("torch:", torch.__version__)
print("cuda available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("cuda device:", torch.cuda.get_device_name(0))
PY
