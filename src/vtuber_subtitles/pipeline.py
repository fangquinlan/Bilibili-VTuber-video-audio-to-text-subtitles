from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from tqdm import tqdm

from .asr import FireRedTranscriber, FireRedTranscriberConfig
from .audio import convert_for_asr, convert_for_separator, ensure_ffmpeg_available
from .downloader import DEFAULT_SERIES_URL, DownloadedItem, download_series_audio, load_downloaded_items, safe_filename
from .models import SEPARATOR_REPO_ID, ensure_firered_models, ensure_separator_model
from .separator import VocalSeparator, VocalSeparatorConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SeriesPipelineConfig:
    series_url: str = DEFAULT_SERIES_URL
    output_root: Path = Path("workspace/bilibili_series_2004017")
    cookies: Path | None = None
    limit: int | None = None
    overwrite: bool = False
    skip_download: bool = False
    skip_separation: bool = False
    skip_asr: bool = False
    model_provider: str = "auto"
    device: str = "auto"
    separator_model_repo: str = SEPARATOR_REPO_ID
    separator_chunk_seconds: float = 30.0
    separator_overlap_seconds: float = 2.0
    separator_batch_size: int = 2
    asr_batch_size: int = 1
    punc_batch_size: int = 4
    hf_token: str | None = None

    def __post_init__(self) -> None:
        self.output_root = Path(self.output_root)
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


class SeriesPipeline:
    def __init__(self, config: SeriesPipelineConfig) -> None:
        self.config = config

    def run(self) -> list[ProcessResult]:
        self._prepare_workspace()
        ensure_ffmpeg_available()

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
                    chunk_seconds=self.config.separator_chunk_seconds,
                    overlap_seconds=self.config.separator_overlap_seconds,
                    batch_size=self.config.separator_batch_size,
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
                    asr_batch_size=self.config.asr_batch_size,
                    punc_batch_size=self.config.punc_batch_size,
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

        self._write_manifest(results)
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

        return download_series_audio(
            series_url=self.config.series_url,
            raw_dir=self.config.raw_dir,
            download_archive=self.config.state_dir / "downloaded.txt",
            cookies=self.config.cookies,
            limit=self.config.limit,
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
        result = transcriber.transcribe_to_text(asr_input, uttid=item.video_id)
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

    def _write_manifest(self, results: list[ProcessResult]) -> None:
        manifest_path = self.config.state_dir / "manifest.jsonl"
        summary_path = self.config.state_dir / "summary.json"
        with manifest_path.open("w", encoding="utf-8") as handle:
            for result in results:
                handle.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")

        summary = {
            "series_url": self.config.series_url,
            "output_root": str(self.config.output_root),
            "total": len(results),
            "done": sum(result.status == "done" for result in results),
            "skipped": sum(result.status == "skipped" for result in results),
            "failed": sum(result.status == "failed" for result in results),
            "results": [asdict(result) for result in results],
        }
        with summary_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
