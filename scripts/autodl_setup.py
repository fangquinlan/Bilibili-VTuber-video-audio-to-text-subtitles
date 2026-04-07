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
DEFAULT_PYTHON_VERSION = "3.11"
DEFAULT_FIRERED_COMMIT = "466c9bb718240132f42ec1b9df14cc6aecae587d"
DEFAULT_CONDA_CREATE_CHANNELS = "defaults"


def parse_channel_list(raw_value: str) -> list[str]:
    return [item for item in raw_value.replace(",", " ").split() if item]


def normalize_python_version(version: str) -> str:
    parts = version.strip().split(".")
    if len(parts) >= 2:
        return ".".join(parts[:2])
    return version.strip()


def build_conda_python_command(
    action: str,
    conda_exe: str,
    env_name: str,
    python_version: str,
    *,
    override_channels: bool = False,
    channels: list[str] | None = None,
) -> list[str]:
    command = [conda_exe, action, "-y", "-n", env_name]
    if override_channels and channels:
        command.append("--override-channels")
        for channel in channels:
            command.extend(["-c", channel])
    command.append(f"python={python_version}")
    return command


def run_conda_python_command_with_fallback(
    action: str,
    conda_exe: str,
    env_name: str,
    python_version: str,
) -> None:
    try:
        run(build_conda_python_command(action, conda_exe, env_name, python_version))
        return
    except subprocess.CalledProcessError:
        fallback_channels = parse_channel_list(env_or_default("CONDA_CREATE_CHANNELS", DEFAULT_CONDA_CREATE_CHANNELS))
        if not fallback_channels:
            raise

        channel_text = ", ".join(fallback_channels)
        print(
            f"Conda {action} failed with the current channel configuration. "
            f"Retrying with override channels: {channel_text}",
            file=sys.stderr,
            flush=True,
        )
        run(
            build_conda_python_command(
                action,
                conda_exe,
                env_name,
                python_version,
                override_channels=True,
                channels=fallback_channels,
            )
        )


def create_conda_env(conda_exe: str, env_name: str, python_version: str) -> None:
    run_conda_python_command_with_fallback("create", conda_exe, env_name, python_version)


def get_env_python_version(conda_exe: str, env_name: str) -> str:
    result = conda_run(
        conda_exe,
        env_name,
        ["python", "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        capture_output=True,
    )
    return result.stdout.strip()


def ensure_env_python_version(conda_exe: str, env_name: str, python_version: str) -> None:
    current_version = normalize_python_version(get_env_python_version(conda_exe, env_name))
    target_version = normalize_python_version(python_version)
    if current_version == target_version:
        return

    print(
        f"Conda env '{env_name}' is using Python {current_version}. "
        f"Upgrading it to Python {target_version} for FireRedASR2S compatibility.",
        flush=True,
    )
    run_conda_python_command_with_fallback("install", conda_exe, env_name, python_version)


def main(argv: list[str] | None = None) -> int:
    _ = argv
    conda_env_name = env_or_default("CONDA_ENV_NAME", DEFAULT_CONDA_ENV_NAME)
    python_version = env_or_default("PYTHON_VERSION", DEFAULT_PYTHON_VERSION)
    firered_commit = env_or_default("FIRERED_COMMIT", DEFAULT_FIRERED_COMMIT)

    install_missing_apt_packages({"git": "git", "ffmpeg": "ffmpeg"})
    conda_exe = require_conda_executable()

    if not conda_env_exists(conda_exe, conda_env_name):
        create_conda_env(conda_exe, conda_env_name, python_version)
    else:
        ensure_env_python_version(conda_exe, conda_env_name, python_version)

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
