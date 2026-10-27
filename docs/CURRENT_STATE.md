---
title: Current state
status: active
updated: 2026-10-27
---

# Current state

## Works today (verified 2026-10-26)

- `python -m vd doctor` — deps, ffmpeg binary, library free space, cookie names, subjects.
- `python -m vd batch <batchId>` — lists a batch's subjects (7 CA Inter subjects found).
- `python -m vd catalog --all` — full tree for every registered subject, including per-video
  notes/DPP/slide lists (Playwright + `curl_cffi`, ~1 min/subject).
- `python -m vd status --all` — per-subject report + `<library>\_SYNC-STATUS.md`.
- `python -m vd download --all --kinds notes,dpp,documents --yes` — **all 673 notes + 14
  e-books/question banks downloaded, 0 failures** (2026-10-26).
- `python -m vd download --subject … --kinds videos --yes` — **one video end to end, verified**:
  "GST in india- An introduction 03" → 3885/3885 segments, ClearKey decrypt, ffmpeg mux →
  577 MB `.mp4`, 2h09m, 1280x720 H.264 + AAC, 1.21 MB/s, 476 s (2026-10-26).
- `python -m vd ui` — browser UI: subjects, plan, selection, catalog/download jobs, log,
  session/settings dialogs, report button, stop button.
- `python -m pytest tests -q` — 113 tests pass (no network, no real library).

## Library snapshot

| Subject (site) | Folder on `G:` | Chapters | Videos local | Notes local |
|---|---|---|---|---|
| Advanced Accounting | `Advance-Accounting` | 14 | 161 | 123 |
| Corporate and Other Law | `Coorporate-And-Other-Law` | 22 | 97 | 93 |
| Taxation | `Taxation` | 16 | 88 | 86 |
| Taxation (GST) | `Taxation (GST)` (new) | 15 | 9 | 63 |
| Cost and Management Accounting | `Cost and Management Accounting` | 19 | 130 | 130 |
| Auditing and Ethics | `Audit` | 12 | 68 | 68 |
| Financial Management and Strategic Management | `Financial-Management-And-Stratigic-Management` | 21 | 110 | 110 |

663 `.mp4` / ≈360 GB total (614 before this rewrite; the tool only adds missing files).
Notes and e-books are complete. **56 videos still missing — GST only** (≈55 GB, 124 GB free);
AA (161/161) and Cost (130/130) are done. GST is capped by the quota below, not by disk or session.

## Blocked / risks

- **Access-key gate — resolved 2026-10-26.** Site ne 2026-10-26 se naya "Generate Access Key" gate
  laga diya tha. Flow: Chrome → `https://stream.testuk.org` → **Generate Access Key** → verification
  complete → DevTools → Application → Cookies → saari `stream.testuk.org` cookies `vd` ke Session
  dialog me paste (`start.bat` → **Session**). Gate dikhe to `vd` ka session dialog wahi steps dikhata
  hai (`stream._BLOCK_MARKERS`). Notes/PDFs par iska koi asar nahi padta (wo direct CDN se aate hain).
- **Video quota — two limits.** `video-url-details` allows **20 videos/hour** *and*
  **50 videos/24 hours** (the daily one only appears in the 429 body: "daily limit of 50 video
  requests in 24 hours"). The runner paces at `videos_per_hour` 18 and `videos_per_day` 45, keeps
  24h of timestamps in `state/video_requests.json`, and **never fails an item on 429** — it waits
  (a 24h limit is polled hourly because slots free one by one). 56 videos ⇒ ≈2 nights.
  Do not launch two `vd download` runs at once — they share the same quota.
- **Disk space.** 56 videos ≈55 GB bache hain, `G:` par ≈124 GB free — fits, par slides
  (thousands of images) + future batches ke liye headroom kam hai. Add `--kinds slides` only
  jab zarurat ho.
- **`G:` drive flakiness.** SanDisk Portable SSD do baar gir chuki hai (volume `Warning`,
  `fsutil dirty query G:` = Dirty, data safe). Runner drive gayab hone par wait karta hai.
  Baaki: cable/port change + USB selective-suspend off, aur idle me `chkdsk G: /f` (admin).
- **Founder:** GST subject naming decide — `Taxation (GST)` is deliberately a separate folder via
  `dir_name`; agar `Taxation` ke andar chahiye to ek `--dir` change plus move.

## Not verified yet

- A full UI click-through (catalog → select → download → report refresh).
- **MCQ:** MCQ *videos* are covered like any other lecture (`MCQ` chapters: AA 34, Cost 14,
  FM&SM 16). MCQ *questions* are **not** on this site: `v3/test-service/tests` returns 0 tests
  for every subject (D-08), so the only offline MCQ practice is those videos + the Law
  `Question Bank (Edition 2)` PDF.

## Next

1. `python -m vd download --all --kinds videos --yes` background me chalta hai — bache hue
   56 GST videos (≈55 GB). Resumable: jo file already hai wo skip hoti hai; 24h quota khatam ho
   to run khud wait karta hai (reset ~20:44 tonight). `G:` drive nikal jaye to wapas lagao.
2. Run ke baad `python -m vd status --all` → `_SYNC-STATUS.md` refresh; failed items retry
   (`--retry-failed`).
3. Slides chahiye ya nahi decide karo (`--kinds slides`, D-02 / SPEC) — disk headroom kam hai.

## Housekeeping

- Legacy one-off scripts (`core_download.py`, `batch_download.py`, `download_materials.py`,
  `_debug_*.py`, `_test_*.py`, scraped `.html`) live in `legacy/` — reference only.
- `stream_cookies.json`, `token.txt`, `pw_headers.json` are gitignored and should be rotated
  once the new `config/cookies.json` flow is in daily use.
