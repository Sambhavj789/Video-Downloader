"""Downloader pacing: the API allows 20 videos/hour, so a run must *wait*, not fail."""

from __future__ import annotations

import asyncio
import time

from vd.config import Settings
from vd.downloader import DownloadRunner


def _runner(tmp_path, per_hour=18):
    settings = Settings(output_root=str(tmp_path), videos_per_hour=per_hour)
    return DownloadRunner(settings, {}, {"key": "k"}, quota_file=tmp_path / "quota.json")


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

def test_saved_window_survives_a_restart(tmp_path):
    """The quota file is what stops a restarted run from burning the hour again."""
    import json

    quota = tmp_path / "quota.json"
    quota.write_text(json.dumps([time.time()] * 3), encoding="utf-8")
    settings = Settings(output_root=str(tmp_path), videos_per_hour=18)
    runner = DownloadRunner(settings, {}, {"key": "k"}, quota_file=quota)
    assert len(runner.video_times) == 3

    runner.video_times.append(time.time())
    runner._save_window()
    assert len(json.loads(quota.read_text(encoding="utf-8"))) == 4

def test_network_blip_is_retried_not_failed(tmp_path):
    """A DNS drop must not kill a 6 hour run."""
    from vd.stream import NetworkError

    runner = _runner(tmp_path)
    calls = {"n": 0}

    async def fake_video(stream, item, index, total):
        calls["n"] += 1
        if calls["n"] == 1:
            raise NetworkError("DNSError: Could not resolve host")
        return True, ""

    async def no_sleep(seconds):
        return None

    runner._download_video = fake_video
    runner._sleep = no_sleep
    ok, error = asyncio.run(runner._download_item(None, {"kind": "videos"}, 1, 1))
    assert ok is True and error == ""
    assert calls["n"] == 2


def test_rate_limit_waits_then_retries_the_same_item(tmp_path):
    from vd.stream import RateLimited

    runner = _runner(tmp_path)
    calls = {"n": 0}
    waits = []

    async def fake_video(stream, item, index, total):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimited("20 videos/hour", 60)
        return True, ""

    async def fake_sleep(seconds):
        waits.append(seconds)

    runner._download_video = fake_video
    runner._sleep = fake_sleep
    ok, _ = asyncio.run(runner._download_item(None, {"kind": "videos"}, 1, 1))
    assert ok is True
    assert waits == [60]
    assert len(runner.video_times) == 1


def test_repeated_network_errors_give_up_eventually(tmp_path):
    from vd.stream import NetworkError

    runner = _runner(tmp_path)
    calls = {"n": 0}

    async def always_fail(stream, item, index, total):
        calls["n"] += 1
        raise NetworkError("offline")

    async def no_sleep(seconds):
        return None

    runner._download_video = always_fail
    runner._sleep = no_sleep
    ok, error = asyncio.run(runner._download_item(None, {"kind": "videos"}, 1, 1))
    assert ok is False
    assert error.startswith("network:")
    assert calls["n"] == 5

def test_missing_drive_makes_the_runner_wait_instead_of_failing(tmp_path):
    """G: has dropped twice; the runner must wait for it, not burn quota on unwritable targets."""
    runner = _runner(tmp_path)
    checks = {"n": 0}

    async def fake_sleep(seconds):
        return None

    runner._sleep = fake_sleep
    runner._target_exists = lambda root: checks.__setitem__("n", checks["n"] + 1) or checks["n"] > 2
    asyncio.run(runner.wait_for_target(tmp_path / "Subject" / "video.mp4"))
    assert checks["n"] == 3


def test_low_free_space_pauses_the_runner(tmp_path, monkeypatch):
    import vd.downloader as downloader_module

    runner = _runner(tmp_path)
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    runner._sleep = fake_sleep
    runner._target_exists = lambda root: True
    values = iter([0.4, 12.0])
    monkeypatch.setattr(downloader_module, "free_space_gb", lambda root: next(values))

    asyncio.run(runner.wait_for_target(tmp_path / "v.mp4"))
    assert waits == [300]
