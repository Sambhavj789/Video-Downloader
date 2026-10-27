---
title: Troubleshooting
status: active
updated: 2026-10-26
---

# Troubleshooting

Start with `python -m vd doctor`. It prints the five things that break most often: deps,
ffmpeg, library free space, cookie names, registered subjects + session probe.

## Session / Cloudflare

| Symptom | Cause | Fix |
|---|---|---|
| `Session: ✗ refresh`, `HTTP 403`, page contains `Just a moment...` | `cf_clearance` expired | Chrome → DevTools → Application → Cookies → `stream.testuk.org` → copy `session` + `cf_clearance` → UI **Session** dialog (or `python -m vd session save cookies.json`) |
| Schedule page title `Generate Access Key — vedstudy`, no `MEDIA_TOKEN` | site's access-key gate (new on 2026-10-26) | Chrome me **Generate Access Key** complete karo, phir saari cookies dobara copy karo. Notes/PDFs isse affect nahi hote |
| Redirects to `/keygenerate` | same as above | same |
| `schedule-details` 200 but no `MEDIA_TOKEN` | lecture not published yet | item stays `unavailable`; retry after the class |
| Cookie file found but empty | saved an empty object | re-paste both cookies |

Never paste cookie values into an issue, a doc or a commit.

## Catalog

| Symptom | Cause | Fix |
|---|---|---|
| `ProxyError: ... HTTP 404 Cannot GET /v2/...` | wrong endpoint version | `batches/<id>/details` is **v3**; `topics`/`contents` are **v2** |
| `Chromium launch fail` | browser not installed for this Python | `python -m playwright install chromium` |
| Catalog saves but 0 notes/DPP/slides | cookies missing → schedule pages skipped silently | fix session, run `catalog` again (add `--deep`) |
| `Is subject me koi chapter nahi mila` | wrong `subjectId` or empty course | `python -m vd batch <batchId>` and re-register |

## Plan / paths

| Symptom | Cause | Fix |
|---|---|---|
| Everything shows `missing` although files exist | filename rule drifted, or wrong folder | compare `names.sanitize` output with the real file; check `dir_name` |
| A new subject folder appeared | the site name did not match any folder closely enough | re-register with `--dir "<existing folder>"`, delete the empty new folder |
| Files land in the wrong subject | fuzzy match picked a too-similar folder | add `dir_name` (D-07) |
| `…  ka catalog nahi hai` | no catalog yet for that subject | `python -m vd catalog --subject <key>` |

## Download

| Symptom | Cause | Fix |
|---|---|---|
| `MPD HTTP 403` right after `item_start` | manifest fetched without browser headers (Cloudflare blocks library UAs) | fixed in `dash.CDN_HEADERS`; if it returns, check that header set is still used for the MPD get |
| `bahut segments fail (x/y)` | CDN throttling, expired signed URL, or missing `Referer` on segments | retry the item; lower `concurrency` in Settings |
| `video-url-details HTTP 429` | the API allows **20 videos/hour** | nothing to fix — the runner waits for the window and retries the same video; `videos_per_hour` (default 18) is the pace |
| `… daily limit of 50 video requests in 24 hours` | the API also allows **50 videos/24h** | nothing to fix — quota is a pause, never a failure; the run waits (polls hourly) and continues by itself. Check `state/video_requests.json` if the wait looks wrong |
| `DRM key nahi mili` | `video-url-details` returned no `keys` | refresh session; if it persists the video uses a different DRM |
| `MPD ne base URL nahi diya` | manifest has neither `URLPrefix` nor absolute segment URLs | should not happen now (`split_mpd_url` falls back to the MPD folder); check the manifest's `SegmentTemplate` |
| `G:` folder "Cannot find drive" mid-run | external drive holding the library disconnected | reconnect the drive, rerun the same command (finished files are skipped) |
| `ffmpeg fail (1): ...` | bad local MPD or incomplete segments | `python -m vd clean`, retry; check the stderr tail in the UI log |
| `.part` files left behind | process killed mid-download | safe to delete; a rerun re-downloads that file |
| `FileNotFoundError: … Notes\…pdf.part` | target path longer than 260 characters (long site titles) | fixed via `names.fs_path`; if it returns, check that writes use `fs_path` not `Path.write_bytes` |
| Download stops by itself with `Session expired` | cookies expired mid-run | refresh session, rerun (finished items are skipped) |

## UI

| Symptom | Cause | Fix |
|---|---|---|
| `Port 7878-7897 sab busy hain` | something else holds the range | close it, or `python -m vd ui --port 8000` |
| Buttons do nothing | `app.js` failed to load | hard refresh (Ctrl+F5); check the browser console |
| Job bar never moves | job finished before polling started | refresh the page; the job snapshot is gone by design |
| Plan list empty | kind chips all off, or `only missing` hides finished items | toggle the chips / the checkbox |

## Tests / docs

| Symptom | Cause | Fix |
|---|---|---|
| `verify-docs.js` → `sources are in CODEMAP` | a new `.py` is not listed | add a row to `docs/CODEMAP.md` |
| `verify-docs.js` → `front matter updated` | missing/invalid `updated:` date | use `YYYY-MM-DD` |
| pytest fails on `settings.output_root` | a test touched the real library | tests must use the `settings` fixture; never `Settings.load()` |
