"""Download runner — executes a plan item by item, resumable, stoppable.

Used by both the CLI and the browser UI. Emits plain dict events so the caller
decides whether to print them or push them to a browser.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import time
from collections import deque
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import dash, names, state
from .config import STATE_DIR, TEMP_DIR, free_space_gb
from .stream import STREAM_BASE, NetworkError, RateLimited, SessionExpired, StreamClient, StreamError

# 429 = quota, 5xx = the site is having a moment; both deserve a retry.
_RETRYABLE_RE = re.compile(r"\b(429|500|502|503|504)\b")

EventFn = Callable[[dict], None]
StopFn = Callable[[], bool]

QUOTA_FILE = STATE_DIR / "video_requests.json"


def _never_stop() -> bool:
    return False


class DownloadRunner:
    def __init__(self, settings, cookies: dict, record: dict, *,
                 on_event: EventFn | None = None, should_stop: StopFn | None = None,
                 quota_file: Path | None = None):
        self.settings = settings
        self.cookies = cookies
        self.record = record
        self.key = record.get("key", "")
        self.on_event = on_event or (lambda event: None)
        self.should_stop = should_stop or _never_stop
        self.quota_file = Path(quota_file) if quota_file else QUOTA_FILE
        self.started = time.time()
        self.bytes_done = 0
        self.download_seconds = 0.0
        self.failed = 0
        self.done = 0
        self.skipped = 0
        self.video_times: deque[float] = deque()
        self._load_window()

    # -- video quota (20/hour and 50/24h on the site) -------------------------
    @property
    def videos_per_hour(self) -> int:
        """The API allows 20 ``video-url-details`` calls/hour; stay under it."""
        return max(1, int(getattr(self.settings, "videos_per_hour", 18) or 18))

    @property
    def videos_per_day(self) -> int:
        """The API also allows only 50 ``video-url-details`` calls/24h."""
        return max(1, int(getattr(self.settings, "videos_per_day", 45) or 45))

    def _trim_window(self) -> None:
        """Keep a full day of timestamps - the 24h limit needs them."""
        cutoff = time.time() - 86400
        while self.video_times and self.video_times[0] < cutoff:
            self.video_times.popleft()

    def _count_since(self, seconds: float) -> int:
        cutoff = time.time() - seconds
        return sum(1 for value in self.video_times if value >= cutoff)

    def _oldest_since(self, seconds: float) -> float:
        cutoff = time.time() - seconds
        for value in self.video_times:
            if value >= cutoff:
                return value
        return time.time()

    def note_video_request(self) -> None:
        """One ``video-url-details`` call is about to be made - count it."""
        self.video_times.append(time.time())
        self._save_window()

    def forget_video_request(self) -> None:
        """The call came back 429, so the server never counted it."""
        if self.video_times:
            self.video_times.pop()
            self._save_window()

    def _load_window(self) -> None:
        """A restarted run must still know how much of the hour is already spent."""
        try:
            saved = json.loads(self.quota_file.read_text(encoding="utf-8"))
            self.video_times.extend(float(value) for value in saved)
        except (OSError, ValueError, TypeError):
            pass
        self._trim_window()

    def _save_window(self) -> None:
        try:
            self.quota_file.parent.mkdir(parents=True, exist_ok=True)
            self.quota_file.write_text(json.dumps(list(self.video_times)), encoding="utf-8")
        except OSError:
            pass

    async def _sleep(self, seconds: float) -> None:
        """Sleep in small steps so ``should_stop`` still works during a long wait."""
        end = time.time() + seconds
        while time.time() < end:
            if self.should_stop():
                return
            await asyncio.sleep(min(10, end - time.time()))

    async def wait_for_video_slot(self) -> None:
        self._trim_window()
        while True:
            if self._count_since(3600) >= self.videos_per_hour:
                oldest = self._oldest_since(3600)
                wait = 3600 - (time.time() - oldest) + 5
                label = f"ghante ki limit ({self.videos_per_hour} videos/hour)"
                reason = "hourly-quota"
            elif len(self.video_times) >= self.videos_per_day:
                oldest = self.video_times[0]
                wait = 86400 - (time.time() - oldest) + 5
                label = f"24 ghante ki limit ({self.videos_per_day} videos/day)"
                reason = "daily-quota"
            else:
                return
            wait = max(wait, 60.0)
            self.log(f"[rate-limit] {label} bhar gayi — {wait / 60:.0f} min wait, phir apne aap chalu")
            self.emit(type="pause", seconds=int(wait), reason=reason)
            await self._sleep(wait)
            if self.should_stop():
                return
            self._trim_window()

    async def wait_for_network(self) -> bool:
        """Laptop slept / WiFi dropped: wait for the site to resolve, don't fail 30 videos.

        Returns False only when the run was asked to stop.
        """
        host = urlparse(STREAM_BASE).hostname or ""
        while True:
            if self.should_stop():
                return False
            try:
                socket.getaddrinfo(host, 443)
                if self._host_reachable(host):
                    self.log("[network] internet wapas aa gaya — continue")
                    return True
            except OSError:
                pass
            self.log(f"[network] {host} resolve nahi ho raha (internet down?) — 2 min par check")
            self.emit(type="pause", seconds=120, reason="network")
            await self._sleep(120)

    @staticmethod
    def _host_reachable(host: str, port: int = 443, timeout: float = 5.0) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def _target_exists(self, root: Path) -> bool:
        try:
            return root.exists()
        except OSError:
            return False

    async def wait_for_target(self, target: Path) -> None:
        """The library SSD has dropped twice — wait for it instead of failing item after item."""
        try:
            root = Path(target.anchor)
        except (OSError, ValueError):  # pragma: no cover - defensive
            return
        if not str(root):
            return
        while not self._target_exists(root):
            self.log(f"[drive] {root} nahi mil raha — wapas lagao, main 60s par check karta rahunga")
            self.emit(type="pause", seconds=60, reason="drive")
            await self._sleep(60)
            if self.should_stop():
                return
        while True:
            free = free_space_gb(root)
            if free is None or free >= 2:
                return
            self.log(f"[drive] {root} par sirf {free} GB free — 5 min wait")
            self.emit(type="pause", seconds=300, reason="space")
            await self._sleep(300)
            if self.should_stop():
                return

    def emit(self, **event) -> None:
        try:
            self.on_event(event)
        except Exception:
            pass

    def log(self, message: str) -> None:
        self.emit(type="log", message=message)

    async def run(self, items: list[dict]) -> dict:
        total = len(items)
        self.emit(type="start", total=total, subject=self.record.get("subject_name", ""))
        stream = StreamClient(self.cookies)
        await stream.__aenter__()
        try:
            for index, item in enumerate(items, start=1):
                if self.should_stop():
                    self.log("stop request mila — ruk raha hoon")
                    break
                target = Path(item["target"])
                if names.stat_size(target) > 0:
                    self.skipped += 1
                    self.emit(type="skip", index=index, total=total, item=item)
                    continue

                await self.wait_for_target(target)
                if self.should_stop():
                    self.log("stop request mila — ruk raha hoon")
                    break

                if item.get("kind") == "videos":
                    await self.wait_for_video_slot()
                    if self.should_stop():
                        self.log("stop request mila — ruk raha hoon")
                        break

                self.emit(type="item_start", index=index, total=total, item=item)
                try:
                    ok, error = await self._download_item(stream, item, index, total)
                except SessionExpired:
                    raise
                except Exception as exc:  # ek item ka crash poora run na girade
                    ok, error = False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"
                if ok:
                    self.done += 1
                    state.mark_done(self.key, item["id"], str(target))
                    self.emit(type="item_done", index=index, total=total, item=item,
                              bytes=self.bytes_done, elapsed=time.time() - self.started,
                              speed_mbps=self.speed_mbps())
                else:
                    self.failed += 1
                    state.mark_failed(self.key, item["id"], error)
                    self.log(f"[fail] {item.get('name', '')[:60]} — {error}")
                    self.emit(type="item_fail", index=index, total=total, item=item, error=error)
        except SessionExpired as exc:
            self.log(f"[session] {exc.detail} — cookies refresh karo (UI > Session)")
            self.emit(type="error", error=f"Session expired: {exc.detail}")
        finally:
            await stream.close()

        summary = {
            "total": total,
            "done": self.done,
            "failed": self.failed,
            "skipped": self.skipped,
            "bytes": self.bytes_done,
            "elapsed_s": round(time.time() - self.started, 1),
        }
        self.emit(type="finish", **summary)
        return summary

    def speed_mbps(self) -> float:
        """Speed over *download* time only — quota waits must not dilute it."""
        elapsed = max(0.5, self.download_seconds or (time.time() - self.started))
        return round(self.bytes_done / (1024 * 1024) / elapsed, 2)

    async def _download_item(self, stream: StreamClient, item: dict,
                             index: int, total: int) -> tuple[bool, str]:
        kind = item["kind"]
        if kind != "videos":
            return await self._download_file(item)
        rate_tries = 0
        net_tries = 0
        while True:
            try:
                return await self._download_video(stream, item, index, total)
            except RateLimited as exc:
                # A quota is not a failure: wait however long it takes, never drop the video.
                rate_tries += 1
                wait = self._rate_wait(exc)
                self.log(
                    f"[rate-limit] {exc} — {wait / 60:.0f} min wait, phir wahi video "
                    f"(try {rate_tries})"
                )
                self.emit(type="pause", seconds=int(wait), reason="rate-limit")
                await self._sleep(wait)
            except NetworkError as exc:
                net_tries += 1
                if net_tries > 4:
                    # Four quick retries failed: treat it as "no internet" and wait it out
                    # instead of burning the rest of the queue (laptop sleep = 30 lost videos).
                    if not await self.wait_for_network():
                        return False, f"network: {exc}"
                    net_tries = 1
                    continue
                wait = min(30.0 * (2 ** (net_tries - 1)), 300.0)
                self.log(f"[network] {exc} — {wait:.0f}s baad dobara (try {net_tries}/4)")
                self.emit(type="pause", seconds=int(wait), reason="network")
                await self._sleep(wait)

    def _rate_wait(self, exc: RateLimited) -> float:
        """Hourly quota clears within the hour; the 24h one frees slots one by one."""
        window = float(getattr(exc, "window", 3600.0) or 3600.0)
        if window > 3900.0:
            return 3600.0
        return max(60.0, min(float(exc.retry_after or 3600.0), 3900.0))

    async def _download_video(self, stream: StreamClient, item: dict,
                              index: int, total: int) -> tuple[bool, str]:
        schedule_id = item.get("schedule_id", "")
        if not schedule_id:
            return False, "schedule id nahi hai"
        try:
            schedule = None
            for attempt in range(4):
                try:
                    schedule = await stream.schedule(
                        self.record["batch_id"], self.record["subject_id"], schedule_id
                    )
                    break
                except SessionExpired:
                    raise
                except RateLimited:
                    raise
                except NetworkError:
                    raise
                except StreamError as exc:
                    # 429 = quota, 5xx = site hiccup: both are worth another look.
                    if attempt == 3 or not _RETRYABLE_RE.search(str(exc)):
                        return False, str(exc)
                    await asyncio.sleep(10 * (attempt + 1))
            if schedule is None:
                return False, "schedule page nahi khula"
            if not schedule.media_token:
                return False, "MEDIA_TOKEN nahi mila"
            self.note_video_request()
            video_data = None
            for attempt in range(4):
                try:
                    video_data = await stream.video_data(schedule.media_token)
                    break
                except RateLimited:
                    self.forget_video_request()  # 429 = the server never counted it
                    raise
                except SessionExpired:
                    raise
                except NetworkError:
                    raise
                except StreamError as exc:
                    if attempt == 3 or not _RETRYABLE_RE.search(str(exc)):
                        return False, str(exc)
                    await asyncio.sleep(10 * (attempt + 1))
            if video_data is None:
                return False, "video-url-details nahi mila"
        except SessionExpired:
            raise
        except RateLimited:
            raise
        except NetworkError:
            raise
        except StreamError as exc:
            return False, str(exc)

        def segment_progress(event: dict) -> None:
            if event.get("phase") == "segments":
                self.emit(type="progress", index=index, total=total, item=item,
                          phase="segments", segments_done=event.get("done", 0),
                          segments_total=event.get("total", 0),
                          segment_failed=event.get("failed", 0),
                          bytes=self.bytes_done + int(event.get("bytes") or 0))
            elif event.get("phase") == "mux":
                self.emit(type="progress", index=index, total=total, item=item, phase="mux")

        temp_dir = TEMP_DIR / f"vid-{abs(hash(item['id'])) % 10_000_000:07d}"
        download_started = time.time()
        result = await dash.download_video(
            video_data, Path(item["target"]), temp_dir,
            quality=self.settings.quality,
            workers=self.settings.concurrency,
            retries=self.settings.retries,
            progress=segment_progress,
        )
        self.download_seconds += time.time() - download_started
        if not result.ok:
            return False, result.error
        self.bytes_done += result.size
        return True, ""

    async def _download_file(self, item: dict) -> tuple[bool, str]:
        import aiohttp

        url = item.get("url", "")
        if not url:
            return False, "url nahi hai"
        target = Path(item["target"])
        Path(names.fs_path(target.parent)).mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        partial_fs = names.fs_path(partial)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Referer": "https://stream.testuk.org/",
        }
        last = "unknown"
        for attempt in range(1, self.settings.retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers,
                                           timeout=aiohttp.ClientTimeout(total=180)) as response:
                        if response.status != 200:
                            last = f"HTTP {response.status}"
                        else:
                            data = await response.read()
                            if not data:
                                last = "khaali file"
                            else:
                                with open(partial_fs, "wb") as handle:
                                    handle.write(data)
                                os.replace(partial_fs, names.fs_path(target))
                                self.bytes_done += len(data)
                                return True, ""
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
            if attempt < self.settings.retries:
                await asyncio.sleep(1.5 * attempt)
        return False, last
