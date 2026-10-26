---
title: Changelog
status: active
updated: 2026-10-26
---

# Changelog

Newest first. One line per user-visible change.

## 2026-10-26 — downloads actually run (CDN headers)

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
