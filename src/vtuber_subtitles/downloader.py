from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

logger = logging.getLogger(__name__)

DEFAULT_SERIES_URL = "https://space.bilibili.com/1878154667/lists/2004017?type=series"


@dataclass(slots=True)
class DownloadedItem:
    playlist_index: int
    video_id: str
    title: str
    uploader: str
    webpage_url: str
    upload_date: str
    source_path: Path
    info_path: Path


def download_series_audio(
    *,
    series_url: str,
    raw_dir: Path,
    download_archive: Path,
    cookies: Path | None = None,
    limit: int | None = None,
) -> list[DownloadedItem]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    download_archive.parent.mkdir(parents=True, exist_ok=True)

    ydl_opts: dict[str, object] = {
        "format": "bestaudio/best",
        "ignoreerrors": True,
        "noplaylist": False,
        "outtmpl": str(raw_dir / "%(id)s" / "source.%(ext)s"),
        "writeinfojson": True,
        "writethumbnail": False,
        "download_archive": str(download_archive),
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
    }
    if cookies is not None:
        ydl_opts["cookiefile"] = str(cookies)
    if limit is not None:
        ydl_opts["playlistend"] = limit

    logger.info("Downloading Bilibili series audio from %s", series_url)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([series_url])

    return load_downloaded_items(raw_dir)


def load_downloaded_items(raw_dir: Path) -> list[DownloadedItem]:
    items: list[DownloadedItem] = []
    for video_dir in sorted(path for path in raw_dir.iterdir() if path.is_dir()):
        info_candidates = sorted(video_dir.glob("*.info.json"))
        if not info_candidates:
            logger.warning("Skipping %s because no info json was found.", video_dir)
            continue

        info_path = info_candidates[0]
        with info_path.open("r", encoding="utf-8") as handle:
            info = json.load(handle)

        source_path = _find_source_audio(video_dir)
        if source_path is None:
            logger.warning("Skipping %s because no downloaded audio file was found.", video_dir)
            continue

        items.append(
            DownloadedItem(
                playlist_index=int(info.get("playlist_index") or len(items) + 1),
                video_id=str(info.get("id") or video_dir.name),
                title=str(info.get("title") or video_dir.name),
                uploader=str(info.get("uploader") or info.get("channel") or ""),
                webpage_url=str(info.get("webpage_url") or info.get("original_url") or ""),
                upload_date=str(info.get("upload_date") or ""),
                source_path=source_path,
                info_path=info_path,
            )
        )

    items.sort(key=lambda item: (item.playlist_index, item.video_id))
    return items


def safe_filename(text: str, fallback: str, max_length: int = 96) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", text).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_length].rstrip(" .")


def _find_source_audio(video_dir: Path) -> Path | None:
    sidecar_suffixes = {
        ".json",
        ".description",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".part",
        ".temp",
        ".ytdl",
    }
    candidates = []
    for path in video_dir.iterdir():
        if not path.is_file():
            continue
        if path.name.endswith(".info.json"):
            continue
        if path.suffix.lower() in sidecar_suffixes:
            continue
        candidates.append(path)

    if not candidates:
        return None
    candidates.sort()
    return candidates[0]
