---
title: Current state
status: active
updated: 2026-10-25
---

# Current state

## Works today (verified 2026-10-25)

- `python -m vd doctor` — deps, ffmpeg binary, library free space, cookie names, subjects.
- `python -m vd batch <batchId>` — lists a batch's subjects (7 CA Inter subjects found).
- `python -m vd catalog --all` — full tree for every registered subject, including per-video
  notes/DPP/slide lists (Playwright + `curl_cffi`, ~1 min/subject).
- `python -m vd status --all` — per-subject report + `<library>\_SYNC-STATUS.md`.
- `python -m vd download ... --dry-run` — prints the exact queue with size estimates.
- `python -m vd ui` — browser UI: subjects, plan, selection, catalog/download jobs, log,
  session/settings dialogs, report button, stop button.
- `python -m pytest tests -q` — 85 tests pass (no network, no real library).

## Library snapshot

| Subject (site) | Folder on `G:` | Chapters | Videos local |
|---|---|---|---|
| Advanced Accounting | `Advance-Accounting` | 14 | 122 |
| Corporate and Other Law | `Coorporate-And-Other-Law` | 22 | 97 |
| Taxation | `Taxation` | 16 | 88 |
| Taxation (GST) | `Taxation (GST)` (new) | 15 | 0 |
| Cost and Management Accounting | `Cost and Management Accounting` | 19 | 129 |
| Auditing and Ethics | `Audit` | 12 | 68 |
| Financial Management and Strategic Management | `Financial-Management-And-Stratigic-Management` | 21 | 110 |

614 `.mp4` / ≈333 GB were already there before this rewrite; the tool adds only missing files.
Videos were the only complete kind — notes/DPP/slides/e-books are almost entirely absent
(2 PDFs in the whole library).

## Blocked / risks

- **Disk space.** `G:` has ≈134 GB free and the remaining PDFs + slides are small, but the
  GST subject and MCQ/revision videos are new content: run `status --all` for the current
  estimate before starting a full sync.
- **Founder:** cookies refresh — Cloudflare `cf_clearance` expires within days; refresh = Chrome se
  manual copy into the Session dialog (no automatic refresh). 2 minute ka kaam, warna download ruk jaata hai.
- **Founder:** GST subject naming decide — `Taxation (GST)` is deliberately a separate folder via
  `dir_name`; agar `Taxation` ke andar chahiye to ek `--dir` change plus move.

## Not verified yet

- One real video end to end (segments → decrypt → mux → playable `.mp4`).
- A full UI click-through (catalog → select → download → report refresh).
- **MCQ:** MCQ *videos* are covered like any other lecture (chapters named `MCQ`, `MCQ ||
  Video Only`). MCQ *questions* live in the site's test service
  (`v3/test-service/tests`) and are **not** supported yet — that needs a new item kind and a
  spec change, not just a download.

## Next

1. `python -m vd download --subject taxation-gst-68dcff --kinds videos --limit 1 --yes`
   and confirm the file plays and then shows `local` in the UI.
2. Download remaining notes/DPP/e-books subject by subject, watching free space (slides are
   opt-in).
3. Decide whether the MCQ test service becomes a new `kind` (needs a spec change first).

## Housekeeping

- Legacy one-off scripts (`core_download.py`, `batch_download.py`, `download_materials.py`,
  `_debug_*.py`, `_test_*.py`, scraped `.html`) live in `legacy/` — reference only.
- `stream_cookies.json`, `token.txt`, `pw_headers.json` are gitignored and should be rotated
  once the new `config/cookies.json` flow is in daily use.
