"""Download runner — executes a plan item by item, resumable, stoppable.

Used by both the CLI and the browser UI. Emits plain dict events so the caller
decides whether to print them or push them to a browser.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from pathlib import Path
from typing import Callable

from . import dash, names, state
from .config import STATE_DIR, TEMP_DIR
from .stream import RateLimited, SessionExpired, StreamClient, StreamError

EventFn = Callable[[dict], None]
StopFn = Callable[[], bool]

QUOTA_FILE = STATE_DIR / "video_requests.json"


def _never_stop() -> bool:
    return False


class DownloadRunner:
    def __init__(self, settings, cookies: dict, record: dict, *,
                 on_event: EventFn | None = None, should_stop: StopFn | None = None):
        self.settings = settings
        self.cookies = cookies
        self.record = record
        self.key = record.get("key", "")
        self.on_event = on_event or (lambda event: None)
        self.should_stop = should_stop or _never_stop
        self.started = time.time()
        self.bytes_done = 0
        self.failed = 0
        self.done = 0
        self.skipped = 0
        self.video_times: deque[float] = deque()
        self._load_window()

    # -- hourly video quota --------------------------------------------------
    @property
    def videos_per_hour(self) -> int:
        """The API allows 20 ``video-url-details`` calls/hour; stay under it."""
        return max(1, int(getattr(self.settings, "videos_per_hour", 18) or 18))

    def _trim_window(self) -> None:
        cutoff = time.time() - 3600
        while self.video_times and self.video_times[0] < cutoff:
            self.video_times.popleft()

    def _load_window(self) -> None:
        """A restarted run must still know how much of the hour is already spent."""
        try:
            saved = json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
            self.video_times.extend(float(value) for value in saved)
        except (OSError, ValueError, TypeError):
            pass
        self._trim_window()

    def _save_window(self) -> None:
        try:
            QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
            QUOTA_FILE.write_text(json.dumps(list(self.video_times)), encoding="utf-8")
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
        while len(self.video_times) >= self.videos_per_hour:
            wait = 3600 - (time.time() - self.video_times[0]) + 5
            self.log(
                f"[rate-limit] ghante ki limit ({self.videos_per_hour} videos/hour) bhar gayi — "
                f"{wait / 60:.0f} min wait, phir apne aap chalu"
            )
            self.emit(type="pause", seconds=int(wait), reason="hourly-quota")
            await self._sleep(wait)
            if self.should_stop():
                return
            self._trim_window()

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

                if item.get("kind") == "videos":
                    await self.wait_for_video_slot()
                    if self.should_stop():
                        self.log("stop request mila — ruk raha hoon")
                        break
                    self.video_times.append(time.time())
                    self._save_window()

                self.emit(type="item_start", index=index, total=total, item=item)
                ok, error = await self._download_item(stream, item, index, total)
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
        elapsed = max(0.5, time.time() - self.started)
        return round(self.bytes_done / (1024 * 1024) / elapsed, 2)

    async def _download_item(self, stream: StreamClient, item: dict,
                             index: int, total: int) -> tuple[bool, str]:
        kind = item["kind"]
        if kind != "videos":
            return await self._download_file(item)
        for attempt in range(4):
            try:
                return await self._download_video(stream, item, index, total)
            except RateLimited as exc:
                if attempt == 3:
                    return False, str(exc)
                wait = max(60.0, min(exc.retry_after, 3900.0))
                self.log(
                    f"[rate-limit] {exc} — {wait / 60:.0f} min wait, phir wahi video "
                    f"(try {attempt + 1}/3)"
                )
                self.emit(type="pause", seconds=int(wait), reason="rate-limit")
                await self._sleep(wait)
                self.video_times.append(time.time())
                self._save_window()
        return False, "rate limit"

    async def _download_video(self, stream: StreamClient, item: dict,
                              index: int, total: int) -> tuple[bool, str]:
        schedule_id = item.get("schedule_id", "")
        if not schedule_id:
            return False, "schedule id nahi hai"
        try:
            schedule = None
            for attempt in range(3):
                try:
                    schedule = await stream.schedule(
                        self.record["batch_id"], self.record["subject_id"], schedule_id
                    )
                    break
                except SessionExpired:
                    raise
                except RateLimited:
                    raise
                except StreamError as exc:
                    if attempt == 2 or "429" not in str(exc):
                        return False, str(exc)
                    await asyncio.sleep(10 * (attempt + 1))
            if schedule is None:
                return False, "schedule page nahi khula"
            if not schedule.media_token:
                return False, "MEDIA_TOKEN nahi mila"
            video_data = await stream.video_data(schedule.media_token)
        except SessionExpired:
            raise
        except RateLimited:
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
        result = await dash.download_video(
            video_data, Path(item["target"]), temp_dir,
            quality=self.settings.quality,
            workers=self.settings.concurrency,
            retries=self.settings.retries,
            progress=segment_progress,
        )
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
