---
title: Changelog
status: active
updated: 2026-10-26
---

# Changelog

Newest first. One line per user-visible change.

## 2026-10-28 - laptop sleep / internet drop no longer kills videos

- 27-Oct night the laptop slept between 05:34 and 10:16 and **30 GST videos were marked
  failed** with `DNSError: Could not resolve host` (four quick retries ≈ 7 minutes is not
  enough for a sleep). `DownloadRunner.wait_for_network` now pauses the run every 2 minutes
  until `stream.testuk.org` resolves *and* accepts a TCP connection, then retries the same
  video — an internet outage is a pause, never a failure (same rule as the quota).
- `tests/test_downloader.py`: one test for "waits then finishes the video", and the give-up
  test now stubs the stop path.

## 2026-10-27 - daily quota (50/24h) + quota misses never fail a video

- The site has a **second** limit: `You have reached the daily limit of 50 video requests in
  24 hours`. `_LIMIT_RE` only knew "in the last N hour", so the daily 429 was treated as an
  hourly wait *and* the third 429 marked the video failed — a night lost after GST Part 05.
- `stream.rate_limit` now reads both windows and sets `RateLimited.window` (3600 / 86400);
  a 24h limit is **polled hourly** (slots free one by one) instead of sleeping a day.
- `DownloadRunner` paces on **two** windows: `videos_per_hour` 18 and `videos_per_day` 45,
  keeping a full day of timestamps in `state/video_requests.json`.
- A 429 no longer counts against the budget (`note_video_request` / `forget_video_request`),
  and `RateLimited` retries are **unbounded** — quota is a pause, never a failure.
- `state/video_requests.json` was seeded from the 49 `.mp4` mtimes of the last 24h (the server
  said 50 requests), so the run waits for the real reset (~20:34) instead of poking the API.
- `vd download` now refuses to plan while the library drive is missing (`_wait_for_output_root`):
  without `G:` every file "looked missing", so a run announced 161 AA videos and would have
  re-downloaded the library. It waits and prints `[drive] G:\ nahi mil raha` instead.

## 2026-10-26 - downloads actually run (CDN headers)

- Video download was failing at the first step (`MPD HTTP 403`): the manifest and every
  segment were fetched with a library user agent, which Cloudflare rejects. Manifest,
  `curl.exe` segments and the `aiohttp` fallback now all send the browser headers
  (`User-Agent` / `Origin` / `Referer`) — see `dash.CDN_HEADERS`.
- New `streamvideo.co.in` manifests carry **no `URLPrefix`** and use relative segment paths
  (`dash/720/$Number$.mp4`); `split_mpd_url` now falls back to the MPD's own folder, which is
  what the DASH spec says. Before this, every segment URL was a bare relative string and the
  whole video "completed" with zero bytes written.
- Segments now download over one keep-alive `aiohttp` session instead of one `curl.exe` per
  segment: 0.35 MB/s → 1.4-2.4 MB/s (default `concurrency` 12; >16 is slower).
  `VD_SEGMENT_FETCHER=curl` restores the old path.
- Long note names (>260 characters once inside `Notes\`) no longer fail with
  `FileNotFoundError`: every write/stat goes through `names.fs_path` (`\\?\` prefix) and
  `names.stat_size`. Six new tests in `tests/test_names.py` / `tests/test_dash.py`.
- Notes/PDF download verified end to end: 2 GST notes landed in
  `G:\Knowledge\CA-Inter\Taxation (GST)\GST in india- An introduction\Notes\`.
- Full notes/e-book sync done: **673 notes + 14 e-books, 0 failures** (7 subjects); first run
  left 49 long-path failures, the `\\?\` fix cleared all of them on the retry.
- The site added an access-key gate on 2026-10-26: schedule pages now answer with a
  `Generate Access Key` page. That page is recognised as a session problem
  (`_BLOCK_MARKERS`) instead of looking like "lecture has no video".

## 2026-10-25 — 2.0.0 (engine rewrite + UI)

- New `vd` package: `link` / `batch` / `catalog` / `status` / `download` / `session` /
  `doctor` / `clean` / `ui` commands replace the old standalone scripts.
- Local browser UI (`python -m vd ui`, `start.bat`): pick a subject, see per-chapter counts,
  tick what is missing, download, watch the log, write the report.
- Metadata now comes from the site's own proxy (`proxy.streamvideo.co.in`, endpoint
  `v3/batches/<id>/details` for subject lists) via headless Chromium — the old
  `api.penpencil.co` Bearer-token path is dead (401).
- `batch` command discovers every subject of a batch and registers it, so no more
  hand-copied subject ids.
- Subject folder is pinned per link (`dir_name`), so `Taxation (GST)` cannot be folded into
  the existing `Taxation` folder, and legacy typos (`Coorporate-And-Other-Law`,
  `Financial-Management-And-Stratigic-Management`) are matched, not replaced.
- Schedule-page rate limits (HTTP 429) are retried with backoff; an unscanned video is
  reported as "unknown", never as "not on the site". `fetch_workers` default is 2 for the
  same reason.
- Default sync = videos + notes + DPP + e-books; slides (hundreds of images per subject) are
  a separate tick/`--kinds slides`.
- Per-subject reports + `<library>\_SYNC-STATUS.md`, and a `status --all` summary.
- `python -m vd clean` removes temp segments, old debug folders and `__pycache__`.
- 80 pytest tests; docs kit (`docs/`, `AGENTS.md`, `verify-docs.js`) added.
- Legacy one-off scripts and scraped HTML moved to `legacy/` (reference only); cookies and
  tokens are gitignored.
## 2026-10-26 — hourly video quota (HTTP 429)

- `video-url-details` is limited to **20 requests per hour** per session/IP; the API says so in the
  429 body ("You have reached the limit of 20 video requests in the last 1 hour"). The old code
  turned that into a normal failure, so a full run wrote 20 videos and then failed the rest.
- `stream.RateLimited` now carries the reset window (server message or `Retry-After`), and the
  downloader **waits and retries the same item** instead of marking it failed.
- `DownloadRunner` also paces itself: at most `videos_per_hour` (default 18) `video-url-details`
  calls per rolling hour, with the timestamps persisted in `state/video_requests.json`, so a
  restarted run does not waste a request on a 429.
## 2026-10-26 — network blips must not kill a run

- `curl_cffi` raises `DNSError`/`ConnectionError` outside the `StreamError` family, so a single
  DNS hiccup crashed a 6 hour video run (observed after video #21: "Could not resolve host").
  `StreamClient.get_text` now wraps those into `stream.NetworkError`, and the runner retries the
  same item with 30s → 300s backoff (4 tries) before marking it failed.
- Any other unexpected exception for one item is now caught per item, so the rest of the queue
  keeps going instead of the whole process dying.
- Reported MB/s is now measured over download time only; long quota waits no longer show up as
  "0.02 MB/s".
## 2026-10-26 — atomic video write (dropped drive)

- ffmpeg used to write straight to the final `.mp4`, so a USB drop mid-mux left a truncated file
  with a non-zero size — and the next run skipped it as "already done". It now muxes to
  `<name>.mp4.part` and `os.replace()`s it into place; failures delete the `.part`.
- The external library SSD (`G:`, SanDisk Portable SSD) dropped twice today and came back NTFS
  *dirty*; a rescan (`Update-HostStorageCache`) restored the volume. All 22 videos downloaded
  before the drop re-checked with ffmpeg: 0 bad files.
## 2026-10-26 — run waits for a missing library drive

- The external SSD dropped twice in one day. Instead of failing every item (which burns the
  hourly quota and bandwidth for nothing), the runner now checks the target drive before each
  item and waits with a log line until it is back; it also pauses when free space is under 2 GB.
## 2026-10-26 — `.part` broke ffmpeg (fixed same hour)

- Writing through `<name>.mp4.part` removed the file extension ffmpeg uses to pick the muxer, so
  every video failed at the last step ("Error initializing the muxer … Invalid argument") while
  the segments had already been downloaded (16 items, ~2 GB wasted).
- The command now passes `-f mp4` explicitly and is built by `_ffmpeg_command()` so a test can
  assert it. Verified with a real video right after the fix.
