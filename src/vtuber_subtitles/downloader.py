from __future__ import annotations

import base64
import hashlib
import html
import http.cookiejar
import json
import logging
import math
import random
import re
import string
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

import yt_dlp

logger = logging.getLogger(__name__)

DEFAULT_SERIES_URL = "https://space.bilibili.com/1878154667/lists/2004017?type=series"
TRACKING_QUERY_KEYS = {
    "spm_id_from",
    "vd_source",
    "from_spmid",
    "from_source",
    "share_source",
    "share_medium",
    "share_plat",
    "share_session_id",
    "share_tag",
    "timestamp",
    "bbid",
    "ts",
}
DEFAULT_SPACE_SEARCH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
WBI_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]


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
    audio_quality: str = "low",
) -> list[DownloadedItem]:
    return download_audio_urls(
        urls=[series_url],
        raw_dir=raw_dir,
        download_archive=download_archive,
        cookies=cookies,
        limit=limit,
        audio_quality=audio_quality,
    )


def download_audio_urls(
    *,
    urls: list[str],
    raw_dir: Path,
    download_archive: Path,
    cookies: Path | None = None,
    limit: int | None = None,
    audio_quality: str = "low",
    url_order_manifest: Path | None = None,
) -> list[DownloadedItem]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    download_archive.parent.mkdir(parents=True, exist_ok=True)

    normalized_urls = dedupe_urls(urls)
    if not normalized_urls:
        raise ValueError("No downloadable URLs were provided.")
    if url_order_manifest is not None:
        _write_url_order_manifest(normalized_urls, url_order_manifest)

    ydl_opts: dict[str, object] = {
        "format": select_audio_format(audio_quality),
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

    logger.info("Downloading %d input URL(s) with audio_quality=%s", len(normalized_urls), audio_quality)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download(normalized_urls)

    return load_downloaded_items(raw_dir, url_order_manifest=url_order_manifest)


def resolve_space_search_urls(
    *,
    space_search_url: str,
    title_must_contain: str | None = None,
    min_duration_minutes: float = 0.0,
    limit: int | None = None,
) -> list[str]:
    mid, keyword = _parse_space_search_url(space_search_url)
    min_duration_seconds = max(0.0, min_duration_minutes) * 60.0
    session = _BilibiliSpaceSearchSession(space_search_url)

    first_page = session.fetch_page(mid=mid, keyword=keyword, page_number=1)
    page_size = int(first_page["page"]["ps"])
    total_count = int(first_page["page"]["count"])
    total_pages = max(1, math.ceil(total_count / page_size))

    matched_urls: list[str] = []
    seen_urls: set[str] = set()
    scanned_items = 0

    for page_number in range(1, total_pages + 1):
        page_data = first_page if page_number == 1 else session.fetch_page(mid=mid, keyword=keyword, page_number=page_number)
        for entry in page_data.get("list", {}).get("vlist", []):
            scanned_items += 1
            title = _clean_space_search_title(str(entry.get("title") or ""))
            if title_must_contain and title_must_contain not in title:
                continue

            duration_seconds = parse_bilibili_duration_to_seconds(str(entry.get("length") or ""))
            if duration_seconds < min_duration_seconds:
                continue

            bvid = str(entry.get("bvid") or "").strip()
            if not bvid:
                continue

            url = f"https://www.bilibili.com/video/{bvid}"
            normalized_url = normalize_source_url(url)
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            matched_urls.append(url)

            logger.info(
                "Matched space search video %s duration=%s title=%s",
                bvid,
                entry.get("length"),
                title,
            )
            if limit is not None and len(matched_urls) >= limit:
                logger.info(
                    "Resolved %d matching video URLs from %s after scanning %d search results.",
                    len(matched_urls),
                    space_search_url,
                    scanned_items,
                )
                return matched_urls

    if not matched_urls:
        raise ValueError(
            "No matching videos were found for the provided Bilibili space search URL. "
            "Try loosening title_must_contain or min_duration_minutes."
        )

    logger.info(
        "Resolved %d matching video URLs from %s after scanning %d search results.",
        len(matched_urls),
        space_search_url,
        scanned_items,
    )
    return matched_urls


def read_input_urls(input_file: Path) -> list[str]:
    urls: list[str] = []
    for raw_line in input_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return dedupe_urls(urls)


def dedupe_urls(urls: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        normalized = normalize_source_url(url)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def normalize_source_url(url: str) -> str:
    split = urlsplit(url.strip())
    query_pairs = []
    for key, value in parse_qsl(split.query, keep_blank_values=False):
        if key in TRACKING_QUERY_KEYS:
            continue
        query_pairs.append((key, value))
    normalized_query = urlencode(sorted(query_pairs))
    normalized_path = split.path.rstrip("/") or "/"
    return urlunsplit((split.scheme, split.netloc, normalized_path, normalized_query, ""))


def select_audio_format(audio_quality: str) -> str:
    quality = audio_quality.lower()
    if quality == "low":
        return "worstaudio/worst/bestaudio/best"
    if quality == "standard":
        return "bestaudio/best"
    if quality == "best":
        return "bestaudio/best"
    raise ValueError(f"Unsupported audio quality: {audio_quality}")


def load_downloaded_items(raw_dir: Path, url_order_manifest: Path | None = None) -> list[DownloadedItem]:
    url_order_map = _load_url_order_manifest(url_order_manifest)
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

        source_url = normalize_source_url(str(info.get("webpage_url") or info.get("original_url") or ""))
        mapped_index = url_order_map.get(source_url)

        items.append(
            DownloadedItem(
                playlist_index=int(mapped_index or info.get("playlist_index") or len(items) + 1),
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


def _parse_space_search_url(space_search_url: str) -> tuple[str, str]:
    split = urlsplit(space_search_url.strip())
    mid_match = re.search(r"^/(\d+)/search/?$", split.path)
    if not mid_match:
        raise ValueError(f"Unsupported Bilibili space search URL: {space_search_url}")

    keyword = parse_qs(split.query).get("keyword", [""])[0].strip()
    if not keyword:
        raise ValueError(f"The Bilibili space search URL is missing a keyword parameter: {space_search_url}")
    return mid_match.group(1), keyword


def _clean_space_search_title(title: str) -> str:
    return re.sub(r"<[^>]+>", "", html.unescape(title)).strip()


def parse_bilibili_duration_to_seconds(text: str) -> int:
    cleaned = text.strip()
    if not cleaned:
        return 0

    parts = cleaned.split(":")
    if not all(part.isdigit() for part in parts):
        return 0

    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total


def _write_url_order_manifest(urls: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        normalize_source_url(url): index
        for index, url in enumerate(urls, start=1)
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _load_url_order_manifest(path: Path | None) -> dict[str, int]:
    if path is None or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        raw_payload = json.load(handle)
    return {
        normalize_source_url(str(url)): int(index)
        for url, index in raw_payload.items()
    }


class _BilibiliSpaceSearchSession:
    def __init__(self, referer_url: str) -> None:
        self.referer_url = referer_url
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookie_jar))
        self._wbi_key_cache: tuple[str, float] | None = None

    def fetch_page(self, *, mid: str, keyword: str, page_number: int) -> dict[str, object]:
        self._prime_session()
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = self._request_json(
                    "https://api.bilibili.com/x/space/wbi/arc/search",
                    headers={
                        "User-Agent": DEFAULT_SPACE_SEARCH_USER_AGENT,
                        "Referer": self.referer_url,
                        "Origin": "https://space.bilibili.com",
                        "Accept": "application/json, text/plain, */*",
                        "Accept-Language": "zh-CN,zh;q=0.9",
                    },
                    query=self._sign_wbi(
                        {
                            "keyword": keyword,
                            "mid": mid,
                            "order": "pubdate",
                            "order_avoided": "true",
                            "platform": "web",
                            "pn": page_number,
                            "ps": 20,
                            "tid": 0,
                            "web_location": "333.1387",
                            "dm_img_list": "[]",
                            "dm_img_str": _random_dm_payload(16, 64),
                            "dm_cover_img_str": _random_dm_payload(32, 128),
                            "dm_img_inter": '{"ds":[],"wh":[6093,6631,31],"of":[430,760,380]}',
                        },
                        video_id=mid,
                    ),
                )
            except HTTPError as exc:
                last_error = exc
                if exc.code == 412 and attempt < 3:
                    logger.warning("Bilibili space search request hit HTTP 412 on attempt %d; retrying.", attempt)
                    time.sleep(1.0 * attempt)
                    self._prime_session(force=True)
                    continue
                raise RuntimeError(
                    "Bilibili space search request was blocked by the server (HTTP 412). "
                    "Please retry later, or provide a different network/IP."
                ) from exc

            code = int(response.get("code", -1))
            if code == 0:
                return dict(response["data"])
            if code == -352 and attempt < 3:
                last_error = RuntimeError("Bilibili space search request was rejected by server (352).")
                logger.warning("Bilibili space search request hit code -352 on attempt %d; retrying.", attempt)
                time.sleep(1.0 * attempt)
                self._prime_session(force=True)
                continue
            raise RuntimeError(f"Bilibili space search request failed ({code}): {response.get('message') or 'Unknown error'}")

        raise RuntimeError("Failed to fetch Bilibili space search results.") from last_error

    def _prime_session(self, force: bool = False) -> None:
        if force or not any(cookie.name == "buvid3" for cookie in self.cookie_jar):
            self._request_text(
                self.referer_url,
                headers={
                    "User-Agent": DEFAULT_SPACE_SEARCH_USER_AGENT,
                    "Referer": "https://www.bilibili.com/",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                },
            )

    def _get_wbi_key(self, video_id: str) -> str:
        if self._wbi_key_cache is not None and time.time() < self._wbi_key_cache[1] + 30:
            return self._wbi_key_cache[0]

        nav_data = self._request_json(
            "https://api.bilibili.com/x/web-interface/nav",
            headers={
                "User-Agent": DEFAULT_SPACE_SEARCH_USER_AGENT,
                "Referer": "https://www.bilibili.com/",
                "Accept": "application/json, text/plain, */*",
            },
        )
        try:
            img_url = nav_data["data"]["wbi_img"]["img_url"]
            sub_url = nav_data["data"]["wbi_img"]["sub_url"]
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"Failed to fetch WBI key for {video_id}.") from exc

        lookup = (
            img_url.rpartition("/")[2].partition(".")[0]
            + sub_url.rpartition("/")[2].partition(".")[0]
        )
        key = "".join(lookup[index] for index in WBI_MIXIN_KEY_ENC_TAB)[:32]
        self._wbi_key_cache = (key, time.time())
        return key

    def _sign_wbi(self, params: dict[str, object], *, video_id: str) -> dict[str, str]:
        signed_params = dict(params)
        signed_params["wts"] = round(time.time())
        normalized_params = {
            key: "".join(character for character in str(value) if character not in "!'()*")
            for key, value in sorted(signed_params.items())
        }
        query = urlencode(normalized_params)
        normalized_params["w_rid"] = hashlib.md5(f"{query}{self._get_wbi_key(video_id)}".encode()).hexdigest()
        return normalized_params

    def _request_text(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        query: dict[str, object] | None = None,
    ) -> str:
        if query:
            url = f"{url}?{urlencode(query)}"
        request = Request(url, headers=headers or {})
        with self.opener.open(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")

    def _request_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        query: dict[str, object] | None = None,
    ) -> dict[str, object]:
        text = self._request_text(url, headers=headers, query=query)
        return json.loads(text)


def _random_dm_payload(min_length: int, max_length: int) -> str:
    return base64.b64encode(
        "".join(random.choices(string.printable, k=random.randint(min_length, max_length))).encode()
    )[:-2].decode()
