---
title: Decisions
status: active
updated: 2026-10-26
---

# Decisions

Newest first. Each entry: what we chose, what we gave up, and what would make us revisit.

## D-08 · "MCQ" means MCQ lecture videos + question-bank PDFs, not test JSON

**Context:** probed the site's test service on 2026-10-26 —
`v3/test-service/tests?batchId=…&subjectId=…` answers `success=true` with **0 tests** for every
CA Inter subject, so there is no question bank to pull as JSON. What the site actually calls MCQ:
`MCQ` / `MCQ || Video Only` chapters (AA 34, Cost 14, FM&SM 16 videos) and a
`Question Bank (Edition 2) || PDF Only` shelf in Law (1 PDF, already a `documents` item).
**Decision:** MCQ is covered by the normal `videos` + `notes`/`documents` kinds. No `mcq` kind
until the test service returns data.
**Cost:** none today; offline MCQ *practice* stays video + PDF only.
**Revisit when:** the test service returns tests for a batch, or a chapter page embeds test ids.

## D-07 · `dir_name` on the link record beats fuzzy matching

**Context:** `Taxation (GST)` normalizes to a string 0.84 similar to `Taxation`, so the fuzzy
matcher would have dropped GST files inside the Income Tax folder.
**Decision:** an explicit `dir_name` is used verbatim; heuristics only run when it is absent.
**Cost:** one extra field in `config/subjects.json` per tricky subject.
**Revisit when:** all folders are named exactly like the site (then the field is redundant).

## D-06 · One job at a time in the UI

**Context:** parallel downloads on one SSD slow each other and the site starts throttling.
**Decision:** `JobManager` allows a single catalog/download job; `video_workers` stays 1.
**Cost:** the UI cannot queue two subjects; the founder waits or stops.
**Revisit when:** a second drive or a fibre link makes parallelism clearly faster.

## D-05 · Metadata through headless Chromium, media through `curl_cffi`

**Context:** `api.penpencil.co` rejects the old Bearer token (401) and the site stopped
embedding `PW_HEADERS`. The new site calls
`proxy.streamvideo.co.in/fetch/api.penpencil.co/...`, which blocks `curl_cffi` with Cloudflare
but answers a real Chromium request context.
**Decision:** Playwright for metadata only; `curl_cffi` (Chrome TLS fingerprint) for
`stream.testuk.org` pages; `curl.exe`/`aiohttp` for CDN segments and PDFs.
**Cost:** Playwright + Chromium are heavy dependencies for what is "just JSON".
**Revisit when:** the proxy stops challenging requests (then plain `aiohttp` suffices).

## D-04 · Disk is the source of truth, progress files are hints

**Context:** the old `batch_progress.json` listed names that no longer matched after the
library was reorganised, which caused silent re-downloads.
**Decision:** `plan` rebuilds status from real files every run; JSON only records failures
worth retrying.
**Cost:** a plan over 600 videos stats a lot of files (still < 1 s).
**Revisit when:** the library lives on network storage where `stat` becomes slow.

## D-03 · Keep the legacy filename rules exactly

**Context:** 614 files on disk were written by `core_download.py`'s `re.sub(r'[<>:"/\\|?*]','_')`.
**Decision:** `names.sanitize` reproduces that rule byte for byte (spaces preserved).
**Cost:** ugly-but-consistent names; no "improvements".
**Revisit when:** the library is migrated wholesale (a separate, founder-approved job).

## D-02 · Attachments get subfolders, PDF-only shelves stay flat

**Context:** the library mixes lecture chapters with shelves named `E-Books __ PDF Only`.
**Decision:** in real chapters → `Notes/`, `DPP/`, `Slides/`; in PDF-only shelves → PDFs
directly at the chapter root.
**Cost:** two path shapes to remember.
**Revisit when:** the site merges shelves into chapters.

## D-01 · Stdlib HTTP server instead of a web framework

**Context:** the founder needs a clickable UI on one machine, not a service.
**Decision:** `http.server` + three static files + JSON endpoints; no build step, no npm.
**Cost:** manual routing and no templating.
**Revisit when:** the UI needs auth, multiple users, or a real-time socket.
