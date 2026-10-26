---
title: Code map
status: active
updated: 2026-10-25
---

# Code map

Symbol-level ownership. Line numbers are omitted on purpose; search the symbol.

## Files

### Engine (`vd/`)

| File | Owns |
|---|---|
| `vd/__init__.py` | package version + docstring |
| `vd/__main__.py` | `python -m vd` entry point |
| `vd/config.py` | all project paths, `Settings` dataclass, `free_space_gb`, `which_curl` |
| `vd/names.py` | sanitize/normalize rules, filename builders, `match_dir` folder matching |
| `vd/layout.py` | where an item lives on disk (subjects, chapters, `Notes/`/`DPP/`/`Slides/`) |
| `vd/links.py` | subject-link registry (`config/subjects.json`), URL build/parse |
| `vd/auth.py` | cookie load/save (never logs values) |
| `vd/proxy.py` | metadata through headless Chromium (`MetadataClient`), pagination |
| `vd/stream.py` | stream-domain pages via `curl_cffi`: schedule parse, `MEDIA_TOKEN`, DRM keys |
| `vd/catalog.py` | site tree → `state/catalogs/<key>.json` |
| `vd/plan.py` | catalog × disk → items with `done`/`missing`/`unavailable` |
| `vd/dash.py` | MPD parse, segment download, ffmpeg mux + ClearKey decrypt |
| `vd/downloader.py` | sequential resumable runner + event stream |
| `vd/report.py` | markdown reports (`per subject` and `_SYNC-STATUS.md`) |
| `vd/state.py` | catalog/progress/report JSON stores, temp cleanup |
| `vd/cli.py` | argparse surface: `link`, `batch`, `catalog`, `status`, `download`, `session`, `doctor`, `clean`, `ui` |
| `vd/ui/__init__.py` | UI package marker |
| `vd/ui/server.py` | stdlib HTTP server, `Job`/`JobManager`, `/api/*` handlers |
| `vd/ui/static/index.html` | the single page (Hindi/Hinglish labels) |
| `vd/ui/static/app.js` | UI state, plan rendering, selection, job polling |
| `vd/ui/static/styles.css` | layout + dark theme |

### Dev helpers (`tools/`)

| File | Owns |
|---|---|
| `tools/probe.py` | print one proxy payload (with `--v2`/`--v3`) |
| `tools/probe_page.py` | summarise embedded arrays on a stream page |
| `tools/fetch_page.py` | save a stream page's HTML to `.dev-pages/` for grepping |

### Tests (`tests/`)

| File | Owns |
|---|---|
| `tests/conftest.py` | `settings`, `record`, `catalog` fixtures (tmp library only) |
| `tests/test_names.py` | legacy name compatibility + folder matching |
| `tests/test_plan.py` | done/missing detection, PDF-only shelves, estimates, dir override |
| `tests/test_state.py` | catalog/progress/report stores, `clean_temp`, legacy trackers |
| `tests/test_dash.py` | MPD parse, track choice, local MPD, segment URLs |
| `tests/test_stream.py` | schedule page parsing, key extraction, block detection |
| `tests/test_proxy.py` | pagination, durations, link round-trip, catalog summary |
| `tests/test_server.py` | API handlers, job events, one real HTTP round-trip |
| `tests/test_report.py` | markdown reports (summary, pipe escaping, library status) |

## Symbols

| Symbol | Responsibility | Invariant |
|---|---|---|
| `names.sanitize()` | Windows-safe name | must equal the name the legacy scripts wrote |
| `names.match_dir()` | find an existing folder | never maps a subject to an unrelated folder (threshold 0.86) |
| `plan.resolve_subject_dir()` | pick the library folder | `dir_name` beats every heuristic |
| `plan.build_plan()` | status per item | pure function; reads disk, never writes |
| `MetadataClient.topics/videos/notes/subjects()` | proxy reads | one browser context reused for the whole catalog |
| `StreamClient.schedule()` | parse a schedule page | raises `SessionExpired`, never silently empties |
| `dash.download_video()` | one video end to end | temp dir removed on success *and* failure |
| `DownloadRunner.run()` | execute items | skips files already on disk; respects stop flag |
| `Job.on_event()` | UI progress mapping | unknown events are ignored, never raise |
| `JobManager.start()` | one job at a time | returns `(False, reason)` when busy |

## Where to change what

### Add a new content type (e.g. "exercises")

1. `vd/proxy.py` — endpoint that lists them.
2. `vd/catalog.py` — attach them to the chapter/video.
3. `vd/plan.py` — new `kind` constant + `_is_selected` filter + estimate.
4. `vd/layout.py` — target folder, `vd/report.py` — a column.
5. `tests/test_plan.py` + `tests/test_proxy.py`, then `docs/SPEC.md`.

### The library folder name must change

1. Rename the folder on `G:` (founder's call).
2. Nothing in code: `match_dir` follows the disk. Only a subject whose site name would
   fuzzy-match the wrong folder needs `dir_name` (`python -m vd link <url> --dir <folder>`).

### Session cookies expired

1. UI → `Session` pill, or `python -m vd session save cookies.json`.
2. `vd/auth.py` is the only writer; `vd/stream.py` is the only reader.

## Test map

| Test | Protects |
|---|---|
| `test_sanitize_keeps_spaces_and_swaps_illegal_chars` | filenames still match the 333 GB library |
| `test_explicit_dir_name_wins_over_fuzzy_match` | `Taxation (GST)` never lands inside `Taxation` |
| `test_plan_sees_existing_files_as_done` | no re-download of finished lectures |
| `test_pdf_only_shelf_keeps_pdfs_at_chapter_root` | PDF shelves keep the old flat shape |
| `test_paged_stops_when_a_page_is_short` | chapter lists are complete |
| `test_choose_tracks_prefers_highest_by_default_and_honours_quality` | quality setting works |
| `test_http_overview_and_job` | UI endpoints answer on a real socket |
| `test_job_manager_marks_a_cancelled_job_stopped` | stop button leaves the UI in a usable state |
| `test_subject_report_escapes_pipes_in_chapter_names` | report table stays valid markdown |

## Invariants and enforcement

| Invariant | Enforced by |
|---|---|
| Cookie/token values never printed or logged | `auth.cookie_summary` returns names only; tests never read secrets |
| Library files are never moved/renamed | code only writes new paths (`plan` is read-only) |
| One download job at a time | `JobManager.start` + tests |
| Missing ≠ unavailable | `plan` marks `unavailable` when the site has no media URL |

## Symptom → first file

| Symptom | Open |
|---|---|
| "Session: ✗ refresh" / 403 pages | `vd/stream.py`, then cookies |
| Catalog builds but 0 notes | `vd/catalog.py` (`_enrich_videos`), cookies needed for schedule pages |
| Everything shows `missing` although files exist | `vd/names.py` sanitize + `vd/plan.py` matching |
| Files land in a new subject folder | `dir_name` missing in `config/subjects.json` |
| ffmpeg error after segments | `vd/dash.py` (`build_local_mpd`, key extraction) |
| UI buttons dead | `vd/ui/static/app.js` + `/api/job` snapshot |
