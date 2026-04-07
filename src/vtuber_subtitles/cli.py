from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .downloader import DEFAULT_SERIES_URL
from .pipeline import SeriesPipeline, SeriesPipelineConfig


def _parse_optional_int(value: str) -> int | None:
    if value.lower() == "auto":
        return None
    return int(value)


def _parse_optional_float(value: str) -> float | None:
    if value.lower() == "auto":
        return None
    return float(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vtuber-subtitles",
        description="Download a Bilibili VTuber series, separate vocals, transcribe with FireRedASR2-AED, and export plain txt subtitles.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run-series", help="Run the full Bilibili VTuber subtitle pipeline.")
    run_parser.add_argument("--series-url", default=DEFAULT_SERIES_URL, help="Bilibili series URL to process.")
    run_parser.add_argument(
        "--space-search-url",
        default=None,
        help="Optional Bilibili uploader search URL like https://space.bilibili.com/<mid>/search?keyword=... . When provided, it takes precedence over input.txt and series-url.",
    )
    run_parser.add_argument(
        "--title-must-contain",
        default=None,
        help="Optional exact substring that every auto-resolved space-search result title must contain.",
    )
    run_parser.add_argument(
        "--max-duration-minutes",
        type=float,
        default=0.0,
        help="Optional maximum duration in minutes for auto-resolved space-search results. Videos longer than this will be filtered out.",
    )
    run_parser.add_argument(
        "--min-duration-minutes",
        dest="max_duration_minutes",
        type=float,
        help=argparse.SUPPRESS,
    )
    run_parser.add_argument(
        "--input-file",
        type=Path,
        default=Path("input.txt"),
        help="Optional txt file with one Bilibili URL per line. If the file exists and is non-empty, it takes precedence over --series-url.",
    )
    run_parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("workspace/bilibili_series_2004017"),
        help="Directory where downloads, models, intermediate files, and txt subtitles will be stored.",
    )
    run_parser.add_argument("--cookies", type=Path, default=None, help="Optional cookies.txt for yt-dlp.")
    run_parser.add_argument("--limit", type=int, default=None, help="Only process the first N videos from the series.")
    run_parser.add_argument("--overwrite", action="store_true", help="Recreate files even if outputs already exist.")
    run_parser.add_argument("--skip-download", action="store_true", help="Reuse existing raw audio files in output_root/raw.")
    run_parser.add_argument("--skip-separation", action="store_true", help="Reuse existing vocals.wav files in output_root/work/*.")
    run_parser.add_argument("--skip-asr", action="store_true", help="Stop after preparing the 16kHz mono vocal tracks.")
    run_parser.add_argument(
        "--model-provider",
        choices=["auto", "huggingface", "modelscope"],
        default="auto",
        help="Where to download FireRed models from. Auto tries ModelScope first, then Hugging Face.",
    )
    run_parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto", help="Inference device for separator and ASR.")
    run_parser.add_argument(
        "--resource-profile",
        choices=["auto", "conservative", "balanced", "aggressive"],
        default="auto",
        help="Auto-tune chunk size and batch sizes for available GPU/RAM, or force a specific profile.",
    )
    run_parser.add_argument("--separator-model-repo", default="HiDolen/Mini-BS-RoFormer-V2-46.8M", help="Hugging Face repo id for the separator model.")
    run_parser.add_argument(
        "--separator-chunk-seconds",
        type=_parse_optional_float,
        default=None,
        help="Separator chunk size in seconds. Omit or use 'auto' to tune from hardware.",
    )
    run_parser.add_argument("--separator-overlap-seconds", type=float, default=2.0, help="Separator overlap size in seconds.")
    run_parser.add_argument(
        "--separator-batch-size",
        type=_parse_optional_int,
        default=None,
        help="Batch size passed to model.separate(). Omit or use 'auto' to tune from hardware.",
    )
    run_parser.add_argument(
        "--asr-batch-size",
        type=_parse_optional_int,
        default=None,
        help="FireRed ASR batch size per VAD segment. Omit or use 'auto' to tune from hardware.",
    )
    run_parser.add_argument(
        "--punc-batch-size",
        type=_parse_optional_int,
        default=None,
        help="FireRed punctuation batch size. Omit or use 'auto' to tune from hardware.",
    )
    run_parser.add_argument(
        "--asr-chunk-minutes",
        type=_parse_optional_float,
        default=None,
        help="Split long vocal tracks into fixed-size chunks before FireRed ASR. Omit or use 'auto' to tune from RAM.",
    )
    run_parser.add_argument(
        "--audio-quality",
        choices=["low", "standard", "best"],
        default="low",
        help="yt-dlp audio selection strategy. Default is low to prefer smaller downloads.",
    )
    run_parser.add_argument("--hf-token", default=None, help="Optional Hugging Face token.")
    run_parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Python logging level.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "run-series":
        config = SeriesPipelineConfig(
            series_url=args.series_url,
            space_search_url=args.space_search_url,
            title_must_contain=args.title_must_contain,
            max_duration_minutes=args.max_duration_minutes,
            input_file=args.input_file,
            output_root=args.output_root,
            cookies=args.cookies,
            limit=args.limit,
            overwrite=args.overwrite,
            skip_download=args.skip_download,
            skip_separation=args.skip_separation,
            skip_asr=args.skip_asr,
            model_provider=args.model_provider,
            device=args.device,
            resource_profile=args.resource_profile,
            separator_model_repo=args.separator_model_repo,
            separator_chunk_seconds=args.separator_chunk_seconds,
            separator_overlap_seconds=args.separator_overlap_seconds,
            separator_batch_size=args.separator_batch_size,
            asr_batch_size=args.asr_batch_size,
            punc_batch_size=args.punc_batch_size,
            asr_chunk_minutes=args.asr_chunk_minutes,
            audio_quality=args.audio_quality,
            hf_token=args.hf_token,
        )
        results = SeriesPipeline(config).run()
        failed = [result for result in results if result.status == "failed"]
        return 1 if failed else 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
