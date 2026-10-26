"""DASH download + ClearKey decrypt + mux (the part that already worked).

Flow per video:

1. parse the MPD (video + audio ``SegmentTemplate``);
2. fetch init + numbered segments into a temp folder (``curl.exe`` when present,
   otherwise ``aiohttp``);
3. write a *local* MPD that points at those files;
4. ``ffmpeg -cenc_decryption_key <key> -c copy`` -> one ``.mp4``.

The decryption key comes from the site's own API (already a ClearKey key even when
``drmType`` says Widevine), so no license server is called.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlparse

from .config import which_curl

NS = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}
ProgressFn = Callable[[dict], None]

# The CDN sits behind Cloudflare: the manifest and every segment answer 403 to
# library-default user agents. These headers are what the browser sends.
CDN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://stream.testuk.org",
    "Referer": "https://stream.testuk.org/",
}

_FFMPEG_CACHE: str | None = None


class DashError(RuntimeError):
    """MPD/manifest problem that retrying will not fix."""


def ffmpeg_exe() -> str:
    """Bundled ``imageio-ffmpeg`` binary first, PATH second."""
    global _FFMPEG_CACHE
    if _FFMPEG_CACHE:
        return _FFMPEG_CACHE
    try:
        import imageio_ffmpeg

        _FFMPEG_CACHE = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        _FFMPEG_CACHE = shutil.which("ffmpeg") or "ffmpeg"
    return _FFMPEG_CACHE


@dataclass
class Track:
    kind: str            # "video" | "audio"
    init: str
    media: str
    count: int
    bandwidth: int
    height: int = 0
    template: dict = field(default_factory=dict)
    timeline: list[dict] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    source_set: ET.Element | None = None

    @property
    def label(self) -> str:
        return f"{self.height}p" if self.kind == "video" else "audio"


@dataclass
class Manifest:
    base_url: str
    auth_query: str
    tracks: list[Track]
    encrypted: bool
    duration: str
    protections: list[ET.Element]


@dataclass
class Result:
    ok: bool
    path: Path | None = None
    size: int = 0
    error: str = ""
    failed_segments: int = 0


def split_mpd_url(mpd_url: str) -> tuple[str, str]:
    """Base URL for the segments, plus the auth query that must ride along.

    Two shapes exist in the wild:

    * old PenPencil MPDs: ``?URLPrefix=<base64 cdn base>&Policy=…`` — the base is in the
      query and the rest is the signed auth string;
    * new ``streamvideo.co.in`` MPDs: no query at all and relative segment paths
      (``dash/720/$Number$.mp4``), so the base is simply the MPD's own folder.
    """
    parsed = urlparse(mpd_url)
    query = parse_qs(parsed.query)
    auth = {k: v[0] for k, v in query.items() if k != "URLPrefix"}
    raw = query.get("URLPrefix", [""])[0]
    if not raw:
        folder = parsed._replace(query="", fragment="").geturl().rsplit("/", 1)[0]
        return (folder + "/" if folder else ""), urlencode(auth)
    padding = "=" * (-len(raw) % 4)
    import base64

    base = base64.b64decode(raw + padding).decode("utf-8").rstrip("/") + "/"
    return base, urlencode(auth)


def count_segments(segment_timeline: ET.Element | None) -> int:
    if segment_timeline is None:
        return 0
    return sum(int(node.get("r", 0)) + 1 for node in segment_timeline.findall("mpd:S", NS))


def parse_manifest(xml_text: str, mpd_url: str) -> Manifest:
    """Read tracks + protection info out of an MPD document."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise DashError(f"MPD parse fail: {exc}") from exc

    base, auth = split_mpd_url(mpd_url)
    tracks: list[Track] = []
    for adaptation in root.findall(".//mpd:AdaptationSet", NS):
        content_type = adaptation.get("contentType", "")
        for representation in adaptation.findall("mpd:Representation", NS):
            template = representation.find("mpd:SegmentTemplate", NS)
            if template is None:
                continue
            timeline = template.find("mpd:SegmentTimeline", NS)
            tracks.append(Track(
                kind=content_type or "video",
                init=template.get("initialization", ""),
                media=template.get("media", ""),
                count=count_segments(timeline),
                bandwidth=int(representation.get("bandwidth", 0) or 0),
                height=int(representation.get("height", 0) or 0),
                template=dict(template.attrib),
                timeline=[dict(node.attrib) for node in (timeline.findall("mpd:S", NS) if timeline is not None else [])],
                attributes={k: representation.get(k) for k in
                            ("id", "bandwidth", "codecs", "mimeType", "width", "height",
                             "audioSamplingRate", "frameRate", "lang") if representation.get(k)},
                source_set=adaptation,
            ))

    if not any(t.kind == "video" for t in tracks):
        raise DashError("MPD me video track nahi mila")
    if not base and any(not t.init.startswith(("http://", "https://")) for t in tracks):
        raise DashError("MPD ne base URL nahi diya (URLPrefix/BaseURL dono missing)")
    return Manifest(
        base_url=base,
        auth_query=auth,
        tracks=tracks,
        encrypted=root.find(".//mpd:ContentProtection", NS) is not None,
        duration=root.get("mediaPresentationDuration", ""),
        protections=list(root.findall(".//mpd:ContentProtection", NS)),
    )


def choose_tracks(manifest: Manifest, quality: str = "best") -> tuple[Track, Track]:
    videos = [t for t in manifest.tracks if t.kind == "video"]
    audios = [t for t in manifest.tracks if t.kind == "audio"]
    if quality and quality != "best":
        try:
            wanted = int(str(quality).rstrip("p"))
            exact = [t for t in videos if t.height == wanted]
            if exact:
                videos = exact
        except ValueError:
            pass
    if not videos:
        raise DashError("MPD me video track nahi mila")
    video = max(videos, key=lambda t: (t.height, t.bandwidth))
    if not audios:
        raise DashError("MPD me audio track nahi mila")
    audio = max(audios, key=lambda t: t.bandwidth)
    return video, audio


def build_local_mpd(manifest: Manifest, video: Track, audio: Track, temp_dir: Path,
                    duration: str = "") -> Path:
    """Rewrite the manifest so ffmpeg reads the segments we just downloaded."""
    ET.register_namespace("", "urn:mpeg:dash:schema:mpd:2011")
    root = ET.Element("{urn:mpeg:dash:schema:mpd:2011}MPD", {
        "profiles": "urn:mpeg:dash:profile:isoff-live:2011",
        "minBufferTime": "PT2S",
        "type": "static",
        "mediaPresentationDuration": duration or manifest.duration or "PT7680S",
    })
    period = ET.SubElement(root, "Period", {"id": "0"})

    for track in (audio, video):
        adaptation = ET.SubElement(period, "AdaptationSet", {
            "contentType": track.kind,
            "segmentAlignment": "true",
            "startWithSAP": "1",
        })
        if track.kind == "audio":
            adaptation.set("lang", "en")
        if track.source_set is not None:
            for protection in track.source_set.findall("mpd:ContentProtection", NS):
                copy = ET.SubElement(adaptation, "ContentProtection", dict(protection.attrib))
                for child in protection:
                    child_copy = ET.SubElement(copy, child.tag, dict(child.attrib))
                    if child.text:
                        child_copy.text = child.text
        representation = ET.SubElement(adaptation, "Representation")
        for key, value in (track.attributes or {}).items():
            if value is None:
                continue
            representation.set(key, value)
        if track.kind == "audio" and track.source_set is not None:
            for channel in track.source_set.findall("mpd:AudioChannelConfiguration", NS):
                ET.SubElement(representation, "AudioChannelConfiguration", dict(channel.attrib))
        segment_template = ET.SubElement(representation, "SegmentTemplate", {
            "timescale": track.template.get("timescale", "1"),
            "initialization": f"{track.label}_init.mp4",
            "media": f"{track.label}_$Number$.mp4",
            "startNumber": "1",
        })
        if track.timeline:
            timeline = ET.SubElement(segment_template, "SegmentTimeline")
            for node in track.timeline:
                ET.SubElement(timeline, "S", node)

    path = temp_dir / "local.mpd"
    path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    return path


def segment_urls(manifest: Manifest, track: Track) -> list[tuple[str, str]]:
    """``[(url, local file name)]`` for init + every segment of one track."""
    suffix = f"?{manifest.auth_query}" if manifest.auth_query else ""
    base = manifest.base_url or ""

    def join(relative: str) -> str:
        if relative.startswith(("http://", "https://")):
            return relative
        return f"{base}{relative}"

    items = [(join(track.init) + (suffix if not track.init.startswith("http") else ""),
              f"{track.label}_init.mp4")]
    for number in range(1, track.count + 1):
        segment = track.media.replace("$Number$", str(number))
        items.append((join(segment) + (suffix if not segment.startswith("http") else ""),
                      f"{track.label}_{number}.mp4"))
    return items


async def _fetch_with_curl(url: str, path: Path, timeout: int) -> bool:
    curl = which_curl()
    if not curl:
        return False
    header_args: list[str] = []
    for name, value in CDN_HEADERS.items():
        header_args += ["-H", f"{name}: {value}"]
    proc = await asyncio.create_subprocess_exec(
        curl, "-s", "-o", str(path), "--connect-timeout", "15",
        "--max-time", str(max(30, timeout)), "-w", "%{http_code}", *header_args, url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0 or not stdout:
        return False
    try:
        return int(stdout.decode().strip()) == 200
    except ValueError:
        return False


class _AiohttpFetcher:
    """Fallback downloader for machines without ``curl.exe``."""

    def __init__(self):
        self._session = None

    async def __aenter__(self):
        import aiohttp

        self._session = aiohttp.ClientSession(headers=dict(CDN_HEADERS))
        return self

    async def __aexit__(self, *exc_info):
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def fetch(self, url: str, path: Path, timeout: int) -> bool:
        import aiohttp

        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                if response.status != 200:
                    return False
                data = await response.read()
                path.write_bytes(data)
                return bool(data)
        except Exception:
            return False


async def _download_segments(items: list[tuple[str, str]], temp_dir: Path, *,
                             workers: int, retries: int, timeout: int,
                             progress: ProgressFn | None = None) -> tuple[int, int]:
    """Download all segments; returns ``(failed, bytes_written)``."""
    queue: asyncio.Queue = asyncio.Queue()
    for url, name in items:
        queue.put_nowait((url, temp_dir / name))
    total = len(items)
    state = {"done": 0, "failed": 0, "bytes": 0}

    # aiohttp keeps the connection alive: ~4x faster than one `curl.exe` per segment
    # (measured 2026-10-26: 0.35 MB/s curl w=3 vs 1.42 MB/s aiohttp w=16).
    try:
        import aiohttp  # noqa: F401
        use_curl = os.environ.get("VD_SEGMENT_FETCHER", "").lower() == "curl"
    except ImportError:  # pragma: no cover - aiohttp is a hard requirement anyway
        use_curl = True
    fetcher = None if use_curl else _AiohttpFetcher()
    if fetcher is not None:
        await fetcher.__aenter__()

    async def worker() -> None:
        while True:
            try:
                url, path = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            ok = False
            for attempt in range(retries):
                try:
                    if use_curl:
                        ok = await _fetch_with_curl(url, path, timeout)
                    else:
                        ok = await fetcher.fetch(url, path, timeout)
                except Exception:
                    ok = False
                if ok:
                    break
                await asyncio.sleep(min(8, 1.5 ** attempt))
            if ok:
                state["bytes"] += path.stat().st_size if path.exists() else 0
            else:
                state["failed"] += 1
            state["done"] += 1
            if progress and (state["done"] % 10 == 0 or state["done"] == total):
                progress({
                    "phase": "segments",
                    "done": state["done"],
                    "total": total,
                    "failed": state["failed"],
                    "bytes": state["bytes"],
                })

    try:
        await asyncio.gather(*(worker() for _ in range(max(1, workers))))
    finally:
        if fetcher is not None:
            await fetcher.__aexit__(None, None, None)
    return state["failed"], state["bytes"]


def _run_ffmpeg(local_mpd: Path, out_path: Path, key: str | None) -> tuple[int, str]:
    command = [ffmpeg_exe()]
    if key:
        command += ["-cenc_decryption_key", key]
    command += ["-i", str(local_mpd), "-c", "copy", "-movflags", "+faststart", "-y", str(out_path)]
    sys.stdout.flush()
    completed = subprocess.run(command, capture_output=True, text=True, errors="replace")
    detail = (completed.stderr or "").strip().splitlines()
    tail = " | ".join(detail[-3:])[:400] if detail else ""
    return completed.returncode, tail


def _safe_remove(path: str) -> None:
    """Best effort: the drive may already be gone."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _mux_to_target(local_mpd: Path, out_path: Path, key: str | None) -> tuple[bool, str, int]:
    """ffmpeg into ``<name>.part``, then rename — a dropped drive never leaves a fake ``.mp4``."""
    from . import names

    temp_path = out_path.with_name(out_path.name + ".part")
    temp_fs = names.fs_path(temp_path)
    out_fs = names.fs_path(out_path)
    code, tail = _run_ffmpeg(local_mpd, temp_fs, key)
    if code != 0 or not os.path.exists(temp_fs):
        _safe_remove(temp_fs)
        return False, f"ffmpeg fail ({code}): {tail}", 0
    try:
        os.replace(temp_fs, out_fs)
    except OSError as exc:
        _safe_remove(temp_fs)
        return False, f"file move fail: {exc}", 0
    return True, "", os.path.getsize(out_fs)


async def download_video(video_data: dict, out_path: Path, temp_dir: Path, *,
                         quality: str = "best", workers: int = 3, retries: int = 4,
                         timeout: int = 60, progress: ProgressFn | None = None) -> Result:
    """Download one video end to end. Never raises for expected failures."""
    out_path = Path(out_path)
    temp_dir = Path(temp_dir)
    try:
        import aiohttp
    except ImportError:  # pragma: no cover
        return Result(ok=False, error="aiohttp install nahi hai")

    try:
        async with aiohttp.ClientSession(headers=dict(CDN_HEADERS)) as session:
            async with session.get(video_data["url"], timeout=aiohttp.ClientTimeout(total=60)) as response:
                if response.status != 200:
                    return Result(ok=False, error=f"MPD HTTP {response.status}")
                xml_text = await response.text()
    except Exception as exc:
        return Result(ok=False, error=f"MPD fetch fail: {type(exc).__name__}")

    try:
        manifest = parse_manifest(xml_text, video_data["url"])
        video_track, audio_track = choose_tracks(manifest, quality)
    except DashError as exc:
        return Result(ok=False, error=str(exc))

    key = video_data.get("_key")
    if manifest.encrypted and not key:
        return Result(ok=False, error=f"DRM key nahi mili ({video_data.get('drmType', 'unknown')})")

    shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    items = segment_urls(manifest, video_track) + segment_urls(manifest, audio_track)
    if progress:
        progress({"phase": "segments", "done": 0, "total": len(items), "failed": 0, "bytes": 0})

    failed, _ = await _download_segments(
        items, temp_dir, workers=workers, retries=retries, timeout=timeout, progress=progress
    )
    if failed > len(items) * 0.5:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return Result(ok=False, error=f"bahut segments fail ({failed}/{len(items)})", failed_segments=failed)

    local_mpd = build_local_mpd(manifest, video_track, audio_track, temp_dir)
    from . import names

    try:
        Path(names.fs_path(out_path.parent)).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return Result(ok=False, error=f"target folder nahi bana: {exc}")
    if progress:
        progress({"phase": "mux", "done": 0, "total": 1, "message": "ffmpeg"})
    ok, error, size = _mux_to_target(local_mpd, out_path, key)
    shutil.rmtree(temp_dir, ignore_errors=True)
    if not ok:
        return Result(ok=False, error=error)
    if progress:
        progress({"phase": "done", "done": 1, "total": 1, "bytes": size})
    return Result(ok=True, path=out_path, size=size, failed_segments=failed)
