---
title: Current state
status: active
updated: 2026-10-26
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
- `python -m vd ui` — browser UI: subjects, plan, selection, catalog/download jobs, log,
  session/settings dialogs, report button, stop button.
- `python -m pytest tests -q` — 91 tests pass (no network, no real library).

## Library snapshot

| Subject (site) | Folder on `G:` | Chapters | Videos local | Notes local |
|---|---|---|---|---|
| Advanced Accounting | `Advance-Accounting` | 14 | 122 | 123 |
| Corporate and Other Law | `Coorporate-And-Other-Law` | 22 | 97 | 93 |
| Taxation | `Taxation` | 16 | 88 | 86 |
| Taxation (GST) | `Taxation (GST)` (new) | 15 | 0 | 63 |
| Cost and Management Accounting | `Cost and Management Accounting` | 19 | 129 | 130 |
| Auditing and Ethics | `Audit` | 12 | 68 | 68 |
| Financial Management and Strategic Management | `Financial-Management-And-Stratigic-Management` | 21 | 110 | 110 |

614 `.mp4` / ≈333 GB were already there before this rewrite; the tool adds only missing files.
Notes and e-books are now complete; **106 videos still missing** (GST 66, AA 39, Cost 1,
≈73 GB) — blocked on the access-key gate below, not on disk space (129 GB free).

## Blocked / risks

- **Founder:** access key — site ne 2026-10-26 se naya "Generate Access Key" gate laga diya.
  Chrome → `https://stream.testuk.org` → **Generate Access Key** → verification complete → DevTools
  → Application → Cookies → saari `stream.testuk.org` cookies `vd` ke Session dialog me paste
  karo (`start.bat` → **Session**). Iske bina schedule page gate dikhata hai aur koi video
  download nahi hota; notes/PDFs par koi asar nahi (wo direct CDN se aate hain).
- **Disk space.** 106 videos ≈73 GB bache hain, `G:` par ≈129 GB free — fits, par slides
  (thousands of images) + future batches ke liye headroom kam hai. Add `--kinds slides` only
  jab zarurat ho.
- **Founder:** GST subject naming decide — `Taxation (GST)` is deliberately a separate folder via
  `dir_name`; agar `Taxation` ke andar chahiye to ek `--dir` change plus move.

## Not verified yet

- One real video end to end (segments → decrypt → mux → playable `.mp4`): the CDN 403 fix is
  proven at the manifest level, but the last full run stopped at the access-key gate.
- A full UI click-through (catalog → select → download → report refresh).
- **MCQ:** MCQ *videos* are covered like any other lecture (`MCQ` chapters: AA 34, Cost 14,
  FM&SM 16). MCQ *questions* are **not** on this site: `v3/test-service/tests` returns 0 tests
  for every subject (D-08), so the only offline MCQ practice is those videos + the Law
  `Question Bank (Edition 2)` PDF.

## Next

1. **Founder:** access key — Chrome me `stream.testuk.org` kholo, **Generate Access Key** complete
   karo, phir DevTools > Application > Cookies ki saari values `start.bat` ke **Session** dialog me
   paste karo. Iske bina bache 106 videos download nahi honge (notes ho chuke).
2. `python -m vd download --all --kinds videos --yes` — bache hue 106 videos (GST 66, AA 39,
   Cost 1). Resumable: jo file already hai wo skip hoti hai.
3. `python -m vd status --all` se `_SYNC-STATUS.md` refresh karo; phir decide karo slides chahiye
   ya nahi (D-02 / SPEC).

## Housekeeping

- Legacy one-off scripts (`core_download.py`, `batch_download.py`, `download_materials.py`,
  `_debug_*.py`, `_test_*.py`, scraped `.html`) live in `legacy/` — reference only.
- `stream_cookies.json`, `token.txt`, `pw_headers.json` are gitignored and should be rotated
  once the new `config/cookies.json` flow is in daily use.
