from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from tqdm import tqdm

from .asr import FireRedTranscriber, FireRedTranscriberConfig
from .audio import convert_for_asr, convert_for_separator, ensure_ffmpeg_available
from .downloader import (
    DEFAULT_SERIES_URL,
    DownloadedItem,
    download_audio_urls,
    download_series_audio,
    load_downloaded_items,
    read_input_urls,
    safe_filename,
)
from .models import SEPARATOR_REPO_ID, ensure_firered_models, ensure_separator_model
from .separator import VocalSeparator, VocalSeparatorConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SeriesPipelineConfig:
    series_url: str = DEFAULT_SERIES_URL
    input_file: Path | None = None
    output_root: Path = Path("workspace/bilibili_series_2004017")
    cookies: Path | None = None
    limit: int | None = None
    overwrite: bool = False
    skip_download: bool = False
    skip_separation: bool = False
    skip_asr: bool = False
    model_provider: str = "auto"
    device: str = "auto"
    resource_profile: str = "auto"
    separator_model_repo: str = SEPARATOR_REPO_ID
    separator_chunk_seconds: float | None = None
    separator_overlap_seconds: float = 2.0
    separator_batch_size: int | None = None
    asr_batch_size: int | None = None
    punc_batch_size: int | None = None
    asr_chunk_minutes: float | None = None
    audio_quality: str = "low"
    hf_token: str | None = None

    def __post_init__(self) -> None:
        self.output_root = Path(self.output_root)
        self.input_file = Path(self.input_file) if self.input_file is not None else None
        self.cookies = Path(self.cookies) if self.cookies is not None else None

    @property
    def raw_dir(self) -> Path:
        return self.output_root / "raw"

    @property
    def work_dir(self) -> Path:
        return self.output_root / "work"

    @property
    def subtitles_dir(self) -> Path:
        return self.output_root / "subtitles"

    @property
    def state_dir(self) -> Path:
        return self.output_root / "state"

    @property
    def models_dir(self) -> Path:
        return self.output_root / "models"

    @property
    def separator_model_dir(self) -> Path:
        return self.models_dir / "Mini-BS-RoFormer-V2-46.8M"

    @property
    def firered_model_root(self) -> Path:
        return self.models_dir / "firered"


@dataclass(slots=True)
class ProcessResult:
    playlist_index: int
    video_id: str
    title: str
    status: str
    subtitle_path: str
    error: str = ""


@dataclass(slots=True)
class ResourceTuning:
    profile: str
    gpu_name: str | None
    gpu_memory_gb: float | None
    system_memory_gb: float | None
    separator_chunk_seconds: float
    separator_batch_size: int
    asr_batch_size: int
    punc_batch_size: int
    asr_chunk_minutes: float


class SeriesPipeline:
    def __init__(self, config: SeriesPipelineConfig) -> None:
        self.config = config

    def run(self) -> list[ProcessResult]:
        self._prepare_workspace()
        ensure_ffmpeg_available()
        tuning = _resolve_resource_tuning(self.config)

        items = self._download_or_load_items()
        if not items:
            raise RuntimeError("No downloaded Bilibili audio files were found.")

        separator = None
        if not self.config.skip_separation:
            ensure_separator_model(
                self.config.separator_model_dir,
                repo_id=self.config.separator_model_repo,
                token=self.config.hf_token,
            )
            separator = VocalSeparator(
                VocalSeparatorConfig(
                    model_dir=self.config.separator_model_dir,
                    device=self.config.device,
                    chunk_seconds=tuning.separator_chunk_seconds,
                    overlap_seconds=self.config.separator_overlap_seconds,
                    batch_size=tuning.separator_batch_size,
                )
            )

        transcriber = None
        if not self.config.skip_asr:
            ensure_firered_models(
                self.config.firered_model_root,
                provider=self.config.model_provider,
                token=self.config.hf_token,
            )
            transcriber = FireRedTranscriber(
                FireRedTranscriberConfig(
                    model_root=self.config.firered_model_root,
                    device=self.config.device,
                    asr_batch_size=tuning.asr_batch_size,
                    punc_batch_size=tuning.punc_batch_size,
                    max_chunk_minutes=tuning.asr_chunk_minutes,
                )
            )

        results: list[ProcessResult] = []
        for item in tqdm(items, desc="Processing videos", unit="video"):
            try:
                results.append(self._process_one(item, separator=separator, transcriber=transcriber))
            except Exception as exc:  # pragma: no cover
                logger.exception("Failed to process %s", item.video_id)
                results.append(
                    ProcessResult(
                        playlist_index=item.playlist_index,
                        video_id=item.video_id,
                        title=item.title,
                        status="failed",
                        subtitle_path="",
                        error=str(exc),
                    )
                )

        merged_subtitle_path = self._write_merged_subtitles(results)
        self._write_manifest(results, tuning=tuning, merged_subtitle_path=merged_subtitle_path)
        return results

    def _prepare_workspace(self) -> None:
        for path in (
            self.config.output_root,
            self.config.raw_dir,
            self.config.work_dir,
            self.config.subtitles_dir,
            self.config.state_dir,
            self.config.models_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def _download_or_load_items(self) -> list[DownloadedItem]:
        if self.config.skip_download:
            logger.info("Skipping download step and reading existing raw audio files from %s", self.config.raw_dir)
            return load_downloaded_items(self.config.raw_dir)

        if self.config.input_file is not None and self.config.input_file.exists():
            urls = read_input_urls(self.config.input_file)
            if urls:
                logger.info("Using %s as the download source list.", self.config.input_file)
                return download_audio_urls(
                    urls=urls,
                    raw_dir=self.config.raw_dir,
                    download_archive=self.config.state_dir / "downloaded.txt",
                    cookies=self.config.cookies,
                    limit=self.config.limit,
                    audio_quality=self.config.audio_quality,
                )
            logger.info("%s exists but contains no usable URLs. Falling back to series_url.", self.config.input_file)

        return download_series_audio(
            series_url=self.config.series_url,
            raw_dir=self.config.raw_dir,
            download_archive=self.config.state_dir / "downloaded.txt",
            cookies=self.config.cookies,
            limit=self.config.limit,
            audio_quality=self.config.audio_quality,
        )

    def _process_one(
        self,
        item: DownloadedItem,
        *,
        separator: VocalSeparator | None,
        transcriber: FireRedTranscriber | None,
    ) -> ProcessResult:
        item_dir = self.config.work_dir / f"{item.playlist_index:03d}_{item.video_id}"
        item_dir.mkdir(parents=True, exist_ok=True)
        subtitle_filename = f"{item.playlist_index:03d}_{item.video_id}_{safe_filename(item.title, item.video_id)}.txt"
        subtitle_path = self.config.subtitles_dir / subtitle_filename

        self._write_item_metadata(item, item_dir)

        if subtitle_path.exists() and not self.config.overwrite and not self.config.skip_asr:
            logger.info("Skipping %s because %s already exists", item.video_id, subtitle_path)
            return ProcessResult(
                playlist_index=item.playlist_index,
                video_id=item.video_id,
                title=item.title,
                status="skipped",
                subtitle_path=str(subtitle_path),
            )

        separator_input = convert_for_separator(
            item.source_path,
            item_dir / "source_44100_stereo.wav",
            overwrite=self.config.overwrite,
        )

        vocals_path = item_dir / "vocals.wav"
        if self.config.skip_separation:
            if not vocals_path.exists():
                raise FileNotFoundError(f"{vocals_path} does not exist but --skip-separation was set.")
        else:
            assert separator is not None
            separator.separate_to_vocals(separator_input, vocals_path, overwrite=self.config.overwrite)

        asr_input = convert_for_asr(
            vocals_path,
            item_dir / "vocals_16000_mono.wav",
            overwrite=self.config.overwrite,
        )

        if self.config.skip_asr:
            return ProcessResult(
                playlist_index=item.playlist_index,
                video_id=item.video_id,
                title=item.title,
                status="prepared",
                subtitle_path="",
            )

        assert transcriber is not None
        result = transcriber.transcribe_to_text(
            asr_input,
            uttid=item.video_id,
            chunk_dir=item_dir / "asr_chunks",
        )
        transcriber.write_outputs(
            result,
            result_json_path=item_dir / "result.json",
            subtitle_txt_path=subtitle_path,
        )
        (item_dir / "subtitle.txt").write_text(str(result.get("text", "")), encoding="utf-8")

        return ProcessResult(
            playlist_index=item.playlist_index,
            video_id=item.video_id,
            title=item.title,
            status="done",
            subtitle_path=str(subtitle_path),
        )

    def _write_item_metadata(self, item: DownloadedItem, item_dir: Path) -> None:
        metadata = {
            "playlist_index": item.playlist_index,
            "video_id": item.video_id,
            "title": item.title,
            "uploader": item.uploader,
            "webpage_url": item.webpage_url,
            "upload_date": item.upload_date,
            "source_path": str(item.source_path),
            "info_path": str(item.info_path),
        }
        with (item_dir / "metadata.json").open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2)

    def _write_merged_subtitles(self, results: list[ProcessResult]) -> str | None:
        merged_blocks: list[str] = []
        for result in sorted(results, key=lambda item: (item.playlist_index, item.video_id)):
            if not result.subtitle_path:
                continue

            subtitle_path = Path(result.subtitle_path)
            if not subtitle_path.exists():
                continue

            text = subtitle_path.read_text(encoding="utf-8").strip()
            if not text:
                continue

            merged_blocks.append(
                "\n".join(
                    [
                        f"### {result.playlist_index:03d} {result.title}",
                        text,
                    ]
                )
            )

        if not merged_blocks:
            return None

        merged_path = self.config.subtitles_dir / "all_subtitles_merged.txt"
        merged_path.write_text("\n\n".join(merged_blocks).rstrip() + "\n", encoding="utf-8")
        logger.info("Wrote merged subtitle text to %s", merged_path)
        return str(merged_path)

    def _write_manifest(
        self,
        results: list[ProcessResult],
        *,
        tuning: ResourceTuning,
        merged_subtitle_path: str | None,
    ) -> None:
        manifest_path = self.config.state_dir / "manifest.jsonl"
        summary_path = self.config.state_dir / "summary.json"
        with manifest_path.open("w", encoding="utf-8") as handle:
            for result in results:
                handle.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")

        summary = {
            "series_url": self.config.series_url,
            "input_file": str(self.config.input_file) if self.config.input_file is not None else None,
            "output_root": str(self.config.output_root),
            "total": len(results),
            "done": sum(result.status == "done" for result in results),
            "skipped": sum(result.status == "skipped" for result in results),
            "failed": sum(result.status == "failed" for result in results),
            "merged_subtitle_path": merged_subtitle_path,
            "resource_tuning": asdict(tuning),
            "results": [asdict(result) for result in results],
        }
        with summary_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)


def _resolve_resource_tuning(config: SeriesPipelineConfig) -> ResourceTuning:
    gpu_name, gpu_memory_gb = _detect_gpu(config.device)
    system_memory_gb = _detect_system_memory_gb()
    profile = _resolve_profile(config.resource_profile, config.device, gpu_memory_gb, system_memory_gb)
    defaults = _profile_defaults(profile)

    tuning = ResourceTuning(
        profile=profile,
        gpu_name=gpu_name,
        gpu_memory_gb=gpu_memory_gb,
        system_memory_gb=system_memory_gb,
        separator_chunk_seconds=config.separator_chunk_seconds or defaults["separator_chunk_seconds"],
        separator_batch_size=config.separator_batch_size or defaults["separator_batch_size"],
        asr_batch_size=config.asr_batch_size or defaults["asr_batch_size"],
        punc_batch_size=config.punc_batch_size or defaults["punc_batch_size"],
        asr_chunk_minutes=config.asr_chunk_minutes or defaults["asr_chunk_minutes"],
    )
    logger.info(
        "Resource tuning profile=%s gpu=%s gpu_memory_gb=%s system_memory_gb=%s "
        "separator_chunk_seconds=%.1f separator_batch_size=%d asr_batch_size=%d "
        "punc_batch_size=%d asr_chunk_minutes=%.1f",
        tuning.profile,
        tuning.gpu_name or "cpu",
        f"{tuning.gpu_memory_gb:.1f}" if tuning.gpu_memory_gb is not None else "n/a",
        f"{tuning.system_memory_gb:.1f}" if tuning.system_memory_gb is not None else "n/a",
        tuning.separator_chunk_seconds,
        tuning.separator_batch_size,
        tuning.asr_batch_size,
        tuning.punc_batch_size,
        tuning.asr_chunk_minutes,
    )
    return tuning


def _resolve_profile(
    requested_profile: str,
    device: str,
    gpu_memory_gb: float | None,
    system_memory_gb: float | None,
) -> str:
    if requested_profile != "auto":
        return requested_profile
    if device == "cpu" or gpu_memory_gb is None:
        return "conservative"
    if gpu_memory_gb >= 24 and (system_memory_gb or 0) >= 64:
        return "aggressive"
    if gpu_memory_gb >= 12:
        return "balanced"
    return "conservative"


def _profile_defaults(profile: str) -> dict[str, float | int]:
    presets: dict[str, dict[str, float | int]] = {
        "conservative": {
            "separator_chunk_seconds": 30.0,
            "separator_batch_size": 2,
            "asr_batch_size": 1,
            "punc_batch_size": 4,
            "asr_chunk_minutes": 20.0,
        },
        "balanced": {
            "separator_chunk_seconds": 45.0,
            "separator_batch_size": 4,
            "asr_batch_size": 4,
            "punc_batch_size": 8,
            "asr_chunk_minutes": 30.0,
        },
        "aggressive": {
            "separator_chunk_seconds": 60.0,
            "separator_batch_size": 8,
            "asr_batch_size": 8,
            "punc_batch_size": 16,
            "asr_chunk_minutes": 45.0,
        },
    }
    if profile not in presets:
        raise ValueError(f"Unsupported resource profile: {profile}")
    return presets[profile]


def _detect_gpu(device: str) -> tuple[str | None, float | None]:
    try:
        import torch
    except ImportError:
        return None, None

    if device == "cpu" or not torch.cuda.is_available():
        return None, None

    torch_device = torch.device("cuda" if device == "auto" else device)
    device_index = torch_device.index if torch_device.index is not None else torch.cuda.current_device()
    properties = torch.cuda.get_device_properties(device_index)
    return properties.name, properties.total_memory / (1024**3)


def _detect_system_memory_gb() -> float | None:
    if hasattr(os, "sysconf"):
        page_size_name = "SC_PAGE_SIZE"
        pages_name = "SC_PHYS_PAGES"
        if page_size_name in os.sysconf_names and pages_name in os.sysconf_names:
            page_size = os.sysconf(page_size_name)
            total_pages = os.sysconf(pages_name)
            if isinstance(page_size, int) and isinstance(total_pages, int) and page_size > 0 and total_pages > 0:
                return page_size * total_pages / (1024**3)
    return None
