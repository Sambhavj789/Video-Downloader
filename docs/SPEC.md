---
title: Spec
status: active
updated: 2026-10-26
---

# Spec

Behavior contract. If code and this file disagree, fix both in the same change.

## Users and jobs

- **Sambhav (non-tech use)** wants to see "kya bacha hai" and download it with a few clicks,
  so whole CA Inter batches are available offline without asking an agent to run scripts.
- **Sambhav (agent/CLI use)** wants the same operations scriptable and testable.

## Scope

**In:** subject registration, chapter/video/notes/DPP/slide catalog, missing-item detection
against the existing library, video (DASH + ClearKey) and PDF/image download, reports, a
local browser UI, doctor/clean commands.

**Out (non-goals):** live note-taking, quiz/MCQ answering, site writes of any kind, uploads,
multi-user access, any UI reachable from another machine, renaming/moving the existing
library, PDF text extraction/OCR.

## Behavior

### Subject registration

- Input: any `stream.testuk.org` URL carrying `batchId` + `subjectId` (a `content` or
  `schedule-details` link), optional `--dir` folder name.
- Rules: key = slug of subject name + first 6 chars of subject id; re-registering the same
  link updates it instead of duplicating.
- Output: record in `config/subjects.json` + `config/links/<key>.txt`.
- Errors: missing ids → `URL me batchId aur subjectId dono chahiye`.

### Batch discovery (`python -m vd batch <id|url>`)

- Lists every subject of a batch (`v3/batches/<id>/details`), hides `Notices`.
- `--add` registers them; `--only "Taxation,Taxation (GST)"` filters by name.
- Output per line: `* <subjectId>  <name>  (<chapters>)`.

### Catalog

- Input: registered subject(s), `--deep` (default) or `--shallow`.
- Rules: chapters from `topics`; videos from `contents?contentType=videos`; PDF-only shelves
  from `contents?contentType=notes` (one schedule per document); every video's schedule page
  is fetched to learn `NOTES`, `DPP_NOTES`, `SLIDES`.
- Output: `state/catalogs/<key>.json` with `chapters[]`, `totals`, `fetched_at`.
- Errors: no chapters → `ProxyError`; expired cookies → `SessionExpired` naming the panel to fix.

### Plan / status

- Input: catalog + library folder + optional `--kinds`, `--chapters`, `--include-done`.
- Rules: a file counts as `done` when the exact name exists and is non-empty, or when a file
  with the same normalized stem does. `unavailable` when the site has no media URL and the
  schedule page was readable; a video whose schedule page could not be read stays `missing`
  (unknown ≠ absent). Default kinds: videos, notes, DPP, e-books — **slides are opt-in**
  (hundreds of images per subject).
- Output: per item `status`, `target`, `size_est_mb`; summary per kind + `selected_est_gb`.
- Errors: no catalog → `FileNotFoundError` telling the user to refresh.

### Download

- Input: selected item ids (UI) or filters (CLI), `--yes` required on the CLI.
- Rules: videos are fetched as MPD segments (parallel, `concurrency`), decrypted with the
  ClearKey from `video-url-details`, muxed by ffmpeg into one `.mp4`; PDFs/images via one
  retrying GET. Existing non-empty target is skipped. One job at a time.
- Every CDN request (manifest, init, segments) must carry browser headers
  (`dash.CDN_HEADERS`: Chrome UA, `Origin`/`Referer` of the site) — Cloudflare answers 403
  to library user agents, which looks like an expired session but is not.
- Output: files in the plan's target paths; `state/progress/<key>.json`; a fresh report.
- Errors: >50 % failed segments → item fails with the count; expired session stops the run
  with a clear message; a single failure never kills the queue.

### UI

- `python -m vd ui` (or `start.bat`) serves `127.0.0.1:7878`, next free port if busy.
- Sections: subjects list, plan (chapters, per-kind checkboxes, search), selection bar
  (count + estimated GB + free space), job bar (percentage, current item, log), dialogs for
  Session, Settings, Add link.
- Endpoints: `GET /api/overview`, `GET /api/plan`, `GET /api/job`, `GET /api/subjects`,
  `POST /api/subjects`, `POST /api/catalog`, `POST /api/download`, `POST /api/job/stop`,
  `POST /api/session`, `POST /api/settings`, `POST /api/status`, `POST /api/clean`,
  `DELETE /api/subjects/<key>`.
- Errors: JSON `{error}` with 4xx/5xx; the UI shows a toast, never a blank screen.

### Reports

- `python -m vd status --all` writes `state/reports/<key>.md` per subject and
  `<library>/_SYNC-STATUS.md` at the root: counts per kind with ✅/⚠️ and the first 40
  missing items.

## Data contracts

```jsonc
// config/subjects.json
{ "<key>": { "key", "url", "batch_id", "subject_id", "batch_name",
             "subject_name", "dir_name", "added_at", "updated_at" } }

// state/catalogs/<key>.json
{ "version": 2, "key", "batch": {"id","name"}, "subject": {"id","name"}, "fetched_at",
  "chapters": [ { "id", "name", "pdf_only",
                  "videos": [ { "id", "topic", "duration_s", "has_media",
                                "notes": [...], "dpp": [...], "slides": [...] } ],
                  "documents": [ { "name", "url", "ext" } ] } ],
  "totals": { "chapters", "videos", "documents", "notes", "dpp", "slides",
              "duration_s", "missing_media" } }

// /api/plan response (items are nested under chapters; the top-level `items` and
// `selected_items` are stripped, only their ids survive in `selected_ids`)
{ "subject", "subject_key", "root", "free_gb", "catalog_at", "kinds",
  "chapters": [ { "name", "dir", "pdf_only", "counts", "items", "selected_count" } ],
  "selected_ids": ["video:<id>", "notes:<hash>"],
  "summary": { "by_kind": { "videos": {"total","done","missing","unavailable"}, ... },
               "selected", "selected_est_mb", "selected_est_gb" } }
```

## Acceptance checks

- [x] `python -m vd doctor` reports deps, ffmpeg, library free space, cookie names, subjects.
- [x] Catalog for a real subject produces chapters with durations and attachment lists.
- [x] `status --all` resolves every registered subject to its existing library folder and
      reports 0 missing videos where the library is complete.
- [x] `python -m pytest tests -q` green (80 tests).
- [ ] One real video download produces a playable file and is then reported as `done`.
- [ ] UI run end to end: catalog → select → download → `_SYNC-STATUS.md` updated.

## Compatibility

- Legacy filename rules are frozen (`names.sanitize`); changing them orphans 614 files.
- `stream_cookies.json` in the project root is still accepted as a fallback cookie source.
- Old scripts (`core_download.py`, `batch_download.py`, `download_materials.py`) are archived
  under `legacy/` as reference only; they are not imported by `vd`.

## Security / privacy

- Cookies (`session`, `cf_clearance`) are read from `config/cookies.json`, never printed,
  never logged, never committed; `auth.cookie_summary` exposes names only.
- The UI listens on loopback; no auth layer because there is no network exposure.
- Requests reuse the founder's own logged-in session; nothing is scraped anonymously and no
  credentials are sent anywhere except the site's own hosts.
