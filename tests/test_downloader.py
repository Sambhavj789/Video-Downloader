"""Downloader pacing: the API allows 20 videos/hour, so a run must *wait*, not fail."""

from __future__ import annotations

import asyncio
import time

from vd.config import Settings
from vd.downloader import DownloadRunner


def _runner(tmp_path, per_hour=18, per_day=45):
    settings = Settings(output_root=str(tmp_path), videos_per_hour=per_hour,
                        videos_per_day=per_day)
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


def test_daily_quota_makes_the_runner_wait_a_day(tmp_path):
    """The site also caps at 50 video requests per 24 hours (hit on 27-Oct 01:29)."""
    runner = _runner(tmp_path, per_hour=1000, per_day=3)
    now = time.time()
    # spread over the day, so the hourly window is not the reason for the wait
    runner.video_times.extend([now - 4000, now - 3000, now - 2000])

    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)
        runner.video_times.clear()  # the day "passes"

    runner._sleep = fake_sleep
    asyncio.run(runner.wait_for_video_slot())

    assert waits, "runner should have waited for the 24h window"
    assert waits[0] > 19 * 3600  # the oldest request must age out of the 24h window


def test_requests_older_than_a_day_do_not_block(tmp_path):
    runner = _runner(tmp_path, per_hour=1000, per_day=1)
    runner.video_times.append(time.time() - 86401)

    async def boom(seconds: float) -> None:  # pragma: no cover - should not run
        raise AssertionError("a day-old request frees the daily slot")

    runner._sleep = boom
    asyncio.run(runner.wait_for_video_slot())


def test_a_429_request_is_not_counted_against_the_quota(tmp_path):
    """Only real requests eat the 50/24h budget; a 429 must not burn a slot."""
    runner = _runner(tmp_path)
    runner.note_video_request()
    assert len(runner.video_times) == 1
    runner.forget_video_request()
    assert len(runner.video_times) == 0

def test_rate_limit_never_drops_the_video(tmp_path):
    """A daily reset can be 19 hours away - the item must survive many 429s."""
    from vd.stream import RateLimited

    runner = _runner(tmp_path)
    calls = {"n": 0}

    async def fake_video(stream, item, index, total):
        calls["n"] += 1
        if calls["n"] <= 5:
            raise RateLimited("daily limit", 3600, window=86400)
        return True, ""

    async def no_sleep(seconds):
        return None

    runner._download_video = fake_video
    runner._sleep = no_sleep
    ok, error = asyncio.run(runner._download_item(None, {"kind": "videos"}, 1, 1))
    assert ok is True and error == ""
    assert calls["n"] == 6


def test_daily_rate_limit_polls_every_hour(tmp_path):
    """A 24h quota frees slots one by one, so waiting a full day would be wrong."""
    from vd.stream import RateLimited

    runner = _runner(tmp_path)
    assert runner._rate_wait(RateLimited("x", 3600, window=86400)) == 3600
    assert runner._rate_wait(RateLimited("x", 3600, window=3600)) == 3600
    assert runner._rate_wait(RateLimited("x", 120, window=3600)) == 120


def test_cli_waits_for_the_drive_before_planning(tmp_path, monkeypatch):
    """Without G: every file looks missing - a run must wait, not re-plan the whole library."""
    from vd import cli

    sleeps: list[float] = []
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: sleeps.append(seconds))
    seen = {"n": 0}

    def fake_exists(path):
        seen["n"] += 1
        return seen["n"] > 2

    cli._wait_for_output_root(str(tmp_path / "lib"), interval=1, exists=fake_exists)
    assert seen["n"] == 3
    assert sleeps == [1, 1]


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
    assert len(runner.video_times) == 0  # the fake never made a request, and a 429 burns no slot


def test_repeated_network_errors_give_up_eventually(tmp_path):
    from vd.stream import NetworkError

    runner = _runner(tmp_path)
    calls = {"n": 0}

    async def always_fail(stream, item, index, total):
        calls["n"] += 1
        raise NetworkError("offline")

    async def no_sleep(seconds):
        return None

    async def no_network():
        return False  # the run was asked to stop

    runner._download_video = always_fail
    runner._sleep = no_sleep
    runner.wait_for_network = no_network
    ok, error = asyncio.run(runner._download_item(None, {"kind": "videos"}, 1, 1))
    assert ok is False
    assert error.startswith("network:")
    assert calls["n"] == 5


def test_laptop_sleep_waits_for_the_internet_instead_of_failing(tmp_path):
    """27-Oct night: laptop slept, 30 GST videos were marked failed on DNS errors."""
    from vd.stream import NetworkError

    runner = _runner(tmp_path)
    calls = {"n": 0}

    async def flaky(stream, item, index, total):
        calls["n"] += 1
        if calls["n"] <= 6:
            raise NetworkError("Could not resolve host: stream.testuk.org")
        return True, ""

    async def no_sleep(seconds):
        return None

    waited = {"n": 0}

    async def net_back():
        waited["n"] += 1
        return True

    runner._download_video = flaky
    runner._sleep = no_sleep
    runner.wait_for_network = net_back
    ok, _ = asyncio.run(runner._download_item(None, {"kind": "videos"}, 1, 1))
    assert ok is True
    assert waited["n"] == 1  # one pause for the network, then the item was retried

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
