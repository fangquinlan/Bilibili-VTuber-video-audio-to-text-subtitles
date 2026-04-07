#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def env_or_default(name: str, default: str) -> str:
    return os.environ.get(name, default)


def find_conda_executable() -> str | None:
    conda_exe = os.environ.get("CONDA_EXE")
    if conda_exe:
        return conda_exe
    return shutil.which("conda")


def require_conda_executable() -> str:
    conda_exe = find_conda_executable()
    if conda_exe:
        return conda_exe
    raise SystemExit("conda was not found in PATH. Please open your AutoDL conda environment first.")


def command_exists(binary: str) -> bool:
    return shutil.which(binary) is not None


def _format_command(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    text_command = [str(part) for part in command]
    print(f"+ {_format_command(text_command)}", flush=True)
    return subprocess.run(
        text_command,
        cwd=cwd or PROJECT_ROOT,
        env=dict(os.environ, **env) if env else None,
        check=check,
        capture_output=capture_output,
        text=True,
    )


def install_missing_apt_packages(packages: Mapping[str, str]) -> None:
    missing = []
    for binary, package_name in packages.items():
        if not command_exists(binary):
            missing.append(package_name)

    if not missing:
        return

    unique_packages = list(dict.fromkeys(missing))
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        apt_prefix = ["apt-get"]
    elif command_exists("sudo"):
        apt_prefix = ["sudo", "apt-get"]
    else:
        package_list = ", ".join(unique_packages)
        raise SystemExit(f"Need root or sudo to install: {package_list}.")

    run([*apt_prefix, "update"])
    run([*apt_prefix, "install", "-y", *unique_packages])


def conda_env_exists(conda_exe: str, env_name: str) -> bool:
    result = run([conda_exe, "env", "list", "--json"], capture_output=True)
    payload = json.loads(result.stdout)
    for env_path in payload.get("envs", []):
        if Path(env_path).name == env_name:
            return True
    return False


@lru_cache(maxsize=None)
def _conda_run_prefix(conda_exe: str) -> tuple[str, ...]:
    help_result = run([conda_exe, "run", "--help"], capture_output=True)
    help_text = f"{help_result.stdout}\n{help_result.stderr}"
    if "--no-capture-output" in help_text:
        return (conda_exe, "run", "--no-capture-output")
    if "--live-stream" in help_text:
        return (conda_exe, "run", "--live-stream")
    return (conda_exe, "run")


def conda_run(
    conda_exe: str,
    env_name: str,
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return run(
        [*_conda_run_prefix(conda_exe), "-n", env_name, *command],
        cwd=cwd,
        env=env,
        check=check,
        capture_output=capture_output,
    )
