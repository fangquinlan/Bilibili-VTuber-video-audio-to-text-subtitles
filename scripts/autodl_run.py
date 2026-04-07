#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

from autodl_common import PROJECT_ROOT, conda_env_exists, conda_run, env_or_default, require_conda_executable

DEFAULT_CONDA_ENV_NAME = "vtuber_subtitles"
DEFAULT_SERIES_URL = "https://space.bilibili.com/1878154667/lists/2004017?type=series"
DEFAULT_OUTPUT_ROOT = str(PROJECT_ROOT / "workspace" / "bilibili_series_2004017")
DEFAULT_MODEL_PROVIDER = "auto"
DEFAULT_DEVICE = "auto"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_INPUT_FILE = str(PROJECT_ROOT / "input.txt")
DEFAULT_AUDIO_QUALITY = "low"


def append_optional_env_arg(args: list[str], env_name: str, flag: str) -> None:
    value = os.environ.get(env_name)
    if value is None or not value.strip():
        return
    args.extend([flag, value.strip()])


def build_base_command() -> list[str]:
    args = [
        "python",
        "-m",
        "vtuber_subtitles.cli",
        "run-series",
        "--series-url",
        env_or_default("SERIES_URL", DEFAULT_SERIES_URL),
        "--input-file",
        env_or_default("INPUT_FILE", DEFAULT_INPUT_FILE),
        "--output-root",
        env_or_default("OUTPUT_ROOT", DEFAULT_OUTPUT_ROOT),
        "--model-provider",
        env_or_default("MODEL_PROVIDER", DEFAULT_MODEL_PROVIDER),
        "--device",
        env_or_default("DEVICE", DEFAULT_DEVICE),
        "--audio-quality",
        env_or_default("AUDIO_QUALITY", DEFAULT_AUDIO_QUALITY),
        "--log-level",
        env_or_default("LOG_LEVEL", DEFAULT_LOG_LEVEL),
    ]
    append_optional_env_arg(args, "RESOURCE_PROFILE", "--resource-profile")
    append_optional_env_arg(args, "SPACE_SEARCH_URL", "--space-search-url")
    append_optional_env_arg(args, "TITLE_MUST_CONTAIN", "--title-must-contain")
    append_optional_env_arg(args, "MIN_DURATION_MINUTES", "--min-duration-minutes")
    append_optional_env_arg(args, "SEPARATOR_CHUNK_SECONDS", "--separator-chunk-seconds")
    append_optional_env_arg(args, "SEPARATOR_OVERLAP_SECONDS", "--separator-overlap-seconds")
    append_optional_env_arg(args, "SEPARATOR_BATCH_SIZE", "--separator-batch-size")
    append_optional_env_arg(args, "ASR_BATCH_SIZE", "--asr-batch-size")
    append_optional_env_arg(args, "PUNC_BATCH_SIZE", "--punc-batch-size")
    append_optional_env_arg(args, "ASR_CHUNK_MINUTES", "--asr-chunk-minutes")
    return args


def main(argv: list[str] | None = None) -> int:
    extra_args = list(sys.argv[1:] if argv is None else argv)
    conda_env_name = env_or_default("CONDA_ENV_NAME", DEFAULT_CONDA_ENV_NAME)
    conda_exe = require_conda_executable()

    if not conda_env_exists(conda_exe, conda_env_name):
        raise SystemExit("Conda env was not found. Run python3 scripts/autodl_setup.py first.")

    result = conda_run(conda_exe, conda_env_name, [*build_base_command(), *extra_args], check=False)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
