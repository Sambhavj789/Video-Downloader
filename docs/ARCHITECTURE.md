---
title: Architecture
status: active
updated: 2026-10-25
---

# Architecture

Two independent halves that meet in one place: **site truth** (catalog) and **disk truth**
(plan). Downloading is just "execute the items the plan marked `missing`".

```
stream.testuk.org (Cloudflare)
   │  cookies: session + cf_clearance          (config/cookies.json)
   ├─ proxy.streamvideo.co.in/fetch/api.penpencil.co/v2|v3   ──► vd/proxy.py   (Playwright)
   │     topics / contents(videos|notes) / batches/<id>/details
   └─ stream.testuk.org/schedule-details + /v1/videos/video-url-details
                                                    ──► vd/stream.py  (curl_cffi)
                                                          │
                                            NOTES / DPP_NOTES / SLIDES / MEDIA_TOKEN
                                                          │
   vd/catalog.py  ──► state/catalogs/<key>.json  (chapters, videos, attachments)
                                                          │
                     vd/plan.py  ◄── vd/layout.py ◄── G:\Knowledge\CA-Inter (real files)
                          │   status: done | missing | unavailable
                          ▼
   vd/downloader.py ──► vd/dash.py (MPD → segments → ffmpeg -cenc_decryption_key)
                          │
                     target .mp4 / .pdf  (library layout unchanged)
```

## Why two clients

| Host | Blocked by | Works with |
|---|---|---|
| `proxy.streamvideo.co.in` | Cloudflare, even for `curl_cffi` | headless **Chromium request context** (`vd/proxy.py`) |
| `stream.testuk.org` | Cloudflare TLS fingerprint check | **`curl_cffi`** `impersonate="chrome124"` + saved cookies (`vd/stream.py`) |
| CDN segments / `static.pw.live` PDFs | signed URLs only | `curl.exe` (fast path) or `aiohttp` |

Neither client is a browser session: no login flow, no page rendering, no JS execution —
only requests.

## Data flow per run

1. `links.add_subject(url)` normalises a site URL into `{batch_id, subject_id, names}` and
   stores it in `config/subjects.json` (+ `config/links/<key>.txt`).
2. `catalog.build_catalog` walks chapters → videos → each video's schedule page and writes
   one JSON tree. This is the only step that needs a browser (= the slow one, ~1 min/subject).
3. `plan.build_plan` resolves the library folder for the subject (`dir_name` wins, else
   exact → normalized → fuzzy match), then marks every catalog item against the filesystem.
4. `downloader.DownloadRunner` executes selected items sequentially; videos go through
   `dash.download_video` (segments in parallel, then one ffmpeg mux), PDFs/images through a
   single retrying HTTP GET. Progress/failures go to `state/progress/<key>.json`.
5. `report.write_subject_report` renders `state/reports/<key>.md`, and `status --all` adds
   `_SYNC-STATUS.md` at the library root.

## UI

`vd/ui/server.py` is a stdlib `http.server` on `127.0.0.1` (no framework, no build step) with
three static files (`index.html`, `app.js`, `styles.css`). It owns exactly one background job
at a time (`JobManager`), because parallel writers on one disk only slow each other down. The
browser polls `GET /api/job` once a second; every action has a CLI equivalent.

## Storage

| Path | Contents | Disposable? |
|---|---|---|
| `G:\Knowledge\CA-Inter\<Subject>\<Chapter>` | the library (videos, `Notes/`, `DPP/`, `Slides/`) | **no** |
| `state/catalogs/<key>.json` | last site snapshot | yes, rebuilt in minutes |
| `state/progress/<key>.json` | done ids, failures worth retrying | yes |
| `state/reports/<key>.md` | human "kya bacha hai" report | yes |
| `.work/` | per-video segment temp | yes (`python -m vd clean`) |
| `config/` | cookies, links, settings (gitignored) | re-enter by hand |

## Boundaries

- The tool never renames, moves or deletes library files; only creates missing ones.
- The tool never touches the site's write APIs (no schedule/test submission).
- The UI binds to loopback only; no port-forwarding, no remote access.
