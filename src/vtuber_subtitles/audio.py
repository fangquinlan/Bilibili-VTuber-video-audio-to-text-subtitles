from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def ensure_ffmpeg_available() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not installed or not in PATH.")


def ffmpeg_convert(
    input_path: Path,
    output_path: Path,
    *,
    sample_rate: int,
    channels: int,
    overwrite: bool,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite:
        return output_path

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-sn",
        "-dn",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-acodec",
        "pcm_s16le",
        str(output_path),
    ]
    subprocess.run(command, check=True)
    return output_path


def convert_for_separator(input_path: Path, output_path: Path, overwrite: bool) -> Path:
    return ffmpeg_convert(
        input_path,
        output_path,
        sample_rate=44100,
        channels=2,
        overwrite=overwrite,
    )


def convert_for_asr(input_path: Path, output_path: Path, overwrite: bool) -> Path:
    return ffmpeg_convert(
        input_path,
        output_path,
        sample_rate=16000,
        channels=1,
        overwrite=overwrite,
    )
