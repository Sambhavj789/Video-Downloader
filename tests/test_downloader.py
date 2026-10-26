"""Downloader pacing: the API allows 20 videos/hour, so a run must *wait*, not fail."""

from __future__ import annotations

import asyncio
import time

from vd.config import Settings
from vd.downloader import DownloadRunner


def _runner(tmp_path, per_hour=18):
    settings = Settings(output_root=str(tmp_path), videos_per_hour=per_hour)
    return DownloadRunner(settings, {}, {"key": "k"})


def test_hourly_quota_makes_the_runner_wait(tmp_path):
    runner = _runner(tmp_path, per_hour=2)
    now = time.time()
    runner.video_times.extend([now, now])

    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)
        runner.video_times.clear()  # the hour "passes"

    runner._sleep = fake_sleep
    asyncio.run(runner.wait_for_video_slot())

    assert waits, "runner should have waited for the window to slide"
    assert waits[0] > 3500


def test_runner_does_not_wait_below_the_quota(tmp_path):
    runner = _runner(tmp_path, per_hour=18)
    runner.video_times.append(time.time())

    async def boom(seconds: float) -> None:  # pragma: no cover - should not run
        raise AssertionError("should not sleep below the quota")

    runner._sleep = boom
    asyncio.run(runner.wait_for_video_slot())


def test_old_requests_fall_out_of_the_window(tmp_path):
    runner = _runner(tmp_path, per_hour=1)
    runner.video_times.append(time.time() - 3601)

    async def boom(seconds: float) -> None:  # pragma: no cover - should not run
        raise AssertionError("an hour-old request frees the slot")

    runner._sleep = boom
    asyncio.run(runner.wait_for_video_slot())
