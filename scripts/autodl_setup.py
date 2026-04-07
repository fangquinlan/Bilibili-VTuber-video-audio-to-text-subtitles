#!/usr/bin/env python3
from __future__ import annotations

import subprocess
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
DEFAULT_CONDA_CREATE_CHANNELS = "defaults"


def parse_channel_list(raw_value: str) -> list[str]:
    return [item for item in raw_value.replace(",", " ").split() if item]


def build_conda_create_command(
    conda_exe: str,
    env_name: str,
    python_version: str,
    *,
    override_channels: bool = False,
    channels: list[str] | None = None,
) -> list[str]:
    command = [conda_exe, "create", "-y", "-n", env_name]
    if override_channels and channels:
        command.append("--override-channels")
        for channel in channels:
            command.extend(["-c", channel])
    command.append(f"python={python_version}")
    return command


def create_conda_env(conda_exe: str, env_name: str, python_version: str) -> None:
    try:
        run(build_conda_create_command(conda_exe, env_name, python_version))
        return
    except subprocess.CalledProcessError:
        fallback_channels = parse_channel_list(env_or_default("CONDA_CREATE_CHANNELS", DEFAULT_CONDA_CREATE_CHANNELS))
        if not fallback_channels:
            raise

        channel_text = ", ".join(fallback_channels)
        print(
            "Conda create failed with the current channel configuration. "
            f"Retrying with override channels: {channel_text}",
            file=sys.stderr,
            flush=True,
        )
        run(
            build_conda_create_command(
                conda_exe,
                env_name,
                python_version,
                override_channels=True,
                channels=fallback_channels,
            )
        )


def main(argv: list[str] | None = None) -> int:
    _ = argv
    conda_env_name = env_or_default("CONDA_ENV_NAME", DEFAULT_CONDA_ENV_NAME)
    python_version = env_or_default("PYTHON_VERSION", DEFAULT_PYTHON_VERSION)
    firered_commit = env_or_default("FIRERED_COMMIT", DEFAULT_FIRERED_COMMIT)

    install_missing_apt_packages({"git": "git", "ffmpeg": "ffmpeg"})
    conda_exe = require_conda_executable()

    if not conda_env_exists(conda_exe, conda_env_name):
        create_conda_env(conda_exe, conda_env_name, python_version)

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
