#!/usr/bin/env python3
from __future__ import annotations

import sys

from autodl_common import (
    PROJECT_ROOT,
    conda_env_exists,
    conda_run,
    env_or_default,
    install_missing_apt_packages,
    require_conda_executable,
    run,
)

DEFAULT_CONDA_ENV_NAME = "vtuber_subtitles"
DEFAULT_PYTHON_VERSION = "3.10"
DEFAULT_FIRERED_COMMIT = "466c9bb718240132f42ec1b9df14cc6aecae587d"


def main(argv: list[str] | None = None) -> int:
    _ = argv
    conda_env_name = env_or_default("CONDA_ENV_NAME", DEFAULT_CONDA_ENV_NAME)
    python_version = env_or_default("PYTHON_VERSION", DEFAULT_PYTHON_VERSION)
    firered_commit = env_or_default("FIRERED_COMMIT", DEFAULT_FIRERED_COMMIT)

    install_missing_apt_packages({"git": "git", "ffmpeg": "ffmpeg"})
    conda_exe = require_conda_executable()

    if not conda_env_exists(conda_exe, conda_env_name):
        run([conda_exe, "create", "-y", "-n", conda_env_name, f"python={python_version}"])

    conda_run(conda_exe, conda_env_name, ["python", "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    conda_run(
        conda_exe,
        conda_env_name,
        ["python", "-m", "pip", "install", "torch", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cu128"],
    )
    conda_run(
        conda_exe,
        conda_env_name,
        ["python", "-m", "pip", "install", "-r", str(PROJECT_ROOT / "requirements.txt")],
    )
    conda_run(
        conda_exe,
        conda_env_name,
        ["python", "-m", "pip", "install", "--no-deps", "-e", str(PROJECT_ROOT)],
    )
    conda_run(
        conda_exe,
        conda_env_name,
        [
            "python",
            "-m",
            "pip",
            "install",
            "--no-deps",
            f"git+https://github.com/FireRedTeam/FireRedASR2S.git@{firered_commit}",
        ],
    )
    conda_run(
        conda_exe,
        conda_env_name,
        [
            "python",
            "-c",
            (
                "import torch; "
                "print('torch:', torch.__version__); "
                "print('cuda available:', torch.cuda.is_available()); "
                "print('cuda device:', torch.cuda.get_device_name(0)) if torch.cuda.is_available() else None"
            ),
        ],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
