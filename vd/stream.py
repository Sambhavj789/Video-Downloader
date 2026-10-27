"""Stream site client (Cloudflare-protected) — cookies + ``curl_cffi`` only.

Per video we need two things from ``stream.testuk.org``:

1. the schedule page (``/schedule-details?...&tap=video``) which embeds
   ``MEDIA_TOKEN``, the note list (``NOTES``), the DPP list (``DPP_NOTES``) and the
   slide frames (``SLIDES``);
2. ``/v1/videos/video-url-details?mediaToken=...`` which returns the signed MPD URL
   plus the ClearKey ``keys`` used to decrypt it.

Nothing here writes cookies or tokens to logs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlencode

STREAM_BASE = "https://stream.testuk.org"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": STREAM_BASE + "/",
}

_ARRAY_RE = r"const\s+{name}\s*=\s*(\[[\s\S]*?\])\s*;"
# Pages that mean "not logged in / not cleared", not "this lecture has no video".
_BLOCK_MARKERS = (
    "keygenerate",
    "just a moment",
    "generate access key",
    "start-key-generation",
)
_TOKEN_RE = re.compile(r'MEDIA_TOKEN\s*=\s*"([^"]+)"')
_VIDEO_DATA_RE = re.compile(
    r"(?:const|var|let|window\.)\s*VIDEO_DATA\s*=\s*({.*?})\s*;", re.DOTALL
)


class StreamError(RuntimeError):
    """Base error for the stream domain."""


class SessionExpired(StreamError):
    """Cookies are stale: the site answers 403 or bounces to ``/keygenerate``."""

    def __init__(self, detail: str = "", status: int = 0):
        super().__init__(detail or "session expired")
        self.detail = detail
        self.status = status


class RateLimited(StreamError):
    """A video-url quota is gone (``HTTP 429``): *wait*, don't fail."""

    def __init__(self, detail: str = "", retry_after: float = 3600.0, window: float = 3600.0):
        super().__init__(detail or "rate limited")
        self.detail = detail
        self.retry_after = retry_after
        self.window = window  # 3600 = hourly quota, 86400 = daily quota


class NetworkError(StreamError):
    """DNS/connection blip — retry the request, never kill a long run."""


_LIMIT_RE = re.compile(
    r"limit of (\d+) (?:video )?requests? in (?:the last )?(\d+) (hour|hours|day|days)", re.I
)


def rate_limit(message: str, headers: dict | None = None) -> RateLimited:
    """Build the exception, preferring the server's own reset window.

    The site has *two* quotas: 20 requests/hour and 50 requests/24 hours. A 24h
    window does not clear in one go (slots free one by one), so we re-check hourly
    instead of sleeping a whole day.
    """
    message = message or ""
    window = 3600.0
    match = _LIMIT_RE.search(message)
    if match:
        unit = match.group(3).lower()
        window = float(match.group(2)) * (86400.0 if unit.startswith("day") else 3600.0)
    wait = window if window <= 3900.0 else 3600.0
    raw = str((headers or {}).get("Retry-After") or "").strip()
    if raw:
        try:
            wait = float(raw)
        except ValueError:
            pass
    return RateLimited(message, max(60.0, min(wait, 3900.0)), window=max(60.0, window))


def _json_message(body: str) -> str:
    try:
        return str(json.loads(body or "").get("message") or "")
    except (json.JSONDecodeError, AttributeError):
        return (body or "")[:200]


@dataclass
class Schedule:
    schedule_id: str
    status: int = 0
    media_token: str = ""
    notes: list[dict] = field(default_factory=list)
    dpp: list[dict] = field(default_factory=list)
    slides: list[dict] = field(default_factory=list)
    topic: str = ""

    @property
    def has_video(self) -> bool:
        return bool(self.media_token)

    def to_dict(self) -> dict:
        return {
            "schedule_id": self.schedule_id,
            "status": self.status,
            "notes": self.notes,
            "dpp": self.dpp,
            "slides": self.slides,
            "has_video": self.has_video,
        }


def parse_js_array(html: str, name: str) -> list[dict]:
    """Read a ``const NAME = [ ... ];`` literal out of the schedule page."""
    match = re.search(_ARRAY_RE.format(name=name), html)
    if not match:
        return []
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def parse_media_token(html: str) -> str:
    match = _TOKEN_RE.search(html)
    return match.group(1) if match else ""


def parse_video_data_block(html: str) -> dict:
    """Older pages embed the whole ``VIDEO_DATA`` object; still supported."""
    match = _VIDEO_DATA_RE.search(html)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def extract_key(video_data: dict) -> str | None:
    """ClearKey hex from ``keys``/``key_strings`` (format ``key_id:key``)."""
    key_strings = video_data.get("key_strings")
    if isinstance(key_strings, str) and "--key " in key_strings:
        parts = key_strings.replace("--key ", "").split(":")
        if len(parts) >= 2:
            return parts[1]

    keys = video_data.get("keys")
    if isinstance(keys, list) and keys:
        parts = str(keys[0]).split(":")
        if len(parts) >= 2:
            return parts[1]
    if isinstance(keys, dict):
        for value in keys.values():
            return str(value)
    return None


class StreamClient:
    """Async client for the Cloudflare-protected stream domain."""

    def __init__(self, cookies: dict, timeout: int = 60, retries: int = 3):
        self.cookies = dict(cookies or {})
        self.timeout = timeout
        self.retries = retries
        self._session = None
        self.last_headers: dict = {}

    async def __aenter__(self) -> "StreamClient":
        from curl_cffi.requests import AsyncSession

        self._session = AsyncSession(impersonate="chrome124")
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    # -- low level -----------------------------------------------------------
    async def get_text(self, url: str, accept: str = "") -> tuple[int, str]:
        if self._session is None:
            raise StreamError("StreamClient start nahi hua (use 'async with').")
        headers = dict(BROWSER_HEADERS)
        if accept:
            headers["Accept"] = accept
        try:
            response = await self._session.get(
                url, headers=headers, cookies=self.cookies, timeout=self.timeout
            )
        except Exception as exc:  # curl_cffi DNSError / ConnectionError / timeout
            raise NetworkError(f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}") from exc
        self.last_headers = dict(response.headers)
        return response.status_code, response.text

    @staticmethod
    def _looks_blocked(status: int, body: str) -> bool:
        if status in (401, 403):
            return True
        lowered = (body or "")[:4000].lower()
        return any(marker in lowered for marker in _BLOCK_MARKERS)

    # -- endpoints -----------------------------------------------------------
    def schedule_url(self, batch_id: str, subject_id: str, schedule_id: str) -> str:
        query = urlencode({
            "batchId": batch_id,
            "subjectId": subject_id,
            "scheduleId": schedule_id,
            "tap": "video",
        })
        return f"{STREAM_BASE}/schedule-details?{query}"

    async def schedule(self, batch_id: str, subject_id: str, schedule_id: str) -> Schedule:
        """Fetch and parse one schedule page (notes, DPP, slides, media token)."""
        status, body = await self.get_text(self.schedule_url(batch_id, subject_id, schedule_id))
        if self._looks_blocked(status, body):
            raise SessionExpired(
                "stream.testuk.org ne access-key/Cloudflare page diya — Chrome me key generate "
                "karke cookies dobara save karo (UI > Session).",
                status,
            )
        if status != 200:
            raise StreamError(f"schedule-details HTTP {status}")
        return Schedule(
            schedule_id=schedule_id,
            status=status,
            media_token=parse_media_token(body),
            notes=parse_js_array(body, "NOTES"),
            dpp=parse_js_array(body, "DPP_NOTES"),
            slides=parse_js_array(body, "SLIDES"),
        )

    async def video_data(self, media_token: str) -> dict:
        """Resolve ``mediaToken`` -> ``{url, drmType, keys, ...}`` for the downloader."""
        query = urlencode({"mediaToken": media_token, "videoContainerType": "DASH"})
        url = f"{STREAM_BASE}/v1/videos/video-url-details?{query}"
        status, body = await self.get_text(url, accept="application/json, text/plain, */*")
        if status == 429:
            raise rate_limit(_json_message(body), self.last_headers)
        if self._looks_blocked(status, body):
            raise SessionExpired(f"video-url-details ne {status} diya.", status)
        if status != 200:
            raise StreamError(f"video-url-details HTTP {status}")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise StreamError("video-url-details ne JSON nahi diya") from exc
        data = payload.get("data") or {}
        if not payload.get("success") or not data.get("url"):
            raise StreamError(f"video-url-details: {payload.get('message') or 'no url'}")
        resolved = {"url": data["url"], "drmType": data.get("drmType") or "ClearKey"}
        for extra in ("keys", "key_strings", "pssh", "licenseUrl", "licenseToken", "certificateUrl"):
            if data.get(extra):
                resolved[extra] = data[extra]
        resolved["_key"] = extract_key(resolved)
        return resolved

    async def check(self, batch_id: str, subject_id: str, schedule_id: str = "") -> dict:
        """Human/UI friendly session probe. Never raises for a bad session."""
        try:
            if schedule_id:
                schedule = await self.schedule(batch_id, subject_id, schedule_id)
                return {
                    "ok": True,
                    "status": schedule.status,
                    "detail": "session valid",
                    "media_token": schedule.has_video,
                }
            status, body = await self.get_text(
                f"{STREAM_BASE}/content?batchId={batch_id}&subjectId={subject_id}"
            )
            if self._looks_blocked(status, body):
                return {"ok": False, "status": status, "detail": "Cloudflare/session block", "media_token": False}
            return {"ok": status == 200, "status": status, "detail": f"content page {status}", "media_token": False}
        except SessionExpired as exc:
            return {"ok": False, "status": exc.status, "detail": exc.detail, "media_token": False}
        except Exception as exc:  # network, DNS, ...
            return {"ok": False, "status": 0, "detail": f"{type(exc).__name__}: {exc}", "media_token": False}


async def check_session(cookies: dict, batch_id: str, subject_id: str,
                        schedule_id: str = "") -> dict:
    """Convenience wrapper used by the CLI, UI and doctor."""
    if not cookies:
        return {"ok": False, "status": 0, "detail": "cookies nahi mile", "media_token": False}
    async with StreamClient(cookies) as client:
        return await client.check(batch_id, subject_id, schedule_id)
