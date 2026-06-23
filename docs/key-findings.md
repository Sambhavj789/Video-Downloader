# Stream.testuk.org Downloader — Key Findings

## 1. Cloudflare & Keygenerate Flow

- `stream.testuk.org` uses Cloudflare to block non-browser clients.
- Visiting `/content?...` first redirects to `/keygenerate` which sets a **stub session cookie**.
- `/keygenerate` redirects through `tipsguru.in` (ads) → back to `stream.testuk.org/keyloginsuccess`.
- `/keyloginsuccess` sets the **real session cookie** (same name `session`, different value).
- The full flow takes 7–10 minutes and often fails mid-way.

## 2. TLS Fingerprint Blocking

- `aiohttp` / `requests` / `httpx` **all blocked** by Cloudflare — TLS fingerprint doesn't match any real browser.
- `curl_cffi` with `impersonate="chrome124"` mimics Chrome's TLS fingerprint perfectly.
- **Only curl_cffi** can reach stream.testuk.org from Python.

```python
from curl_cffi.requests import AsyncSession
async with AsyncSession(impersonate="chrome124") as sess:
    resp = await sess.get(url, headers=headers, cookies=cookies)
```

## 3. Real vs Stub Session Cookie

| Cookie | Set by | Works? |
|--------|--------|--------|
| `session` (stub) | `/keygenerate` | ❌ Redirects back to keygenerate |
| `session` (real) | `/keyloginsuccess` | ✅ Bypasses keygenerate entirely |

With the **real** session cookie + `cf_clearance`, curl_cffi can access stream.testuk.org directly — no browser/Playwright needed at all.

**Where to get them**: Chrome → DevTools → Application → Cookies → `stream.testuk.org` → copy `cf_clearance` and `session` values → paste into `stream_cookies.json`.

## 4. Two Endpoints, Different Responses

| Endpoint | Response Size | Contains | 
|----------|---------------|----------|
| `/content?batchId=...&subjectId=...&scheduleId=...` | ~9 KB | Minimal wrapper page, no video data |
| `/schedule-details?batchId=...&subjectId=...&scheduleId=...&tap=video` | ~83 KB | Full video page with MEDIA_TOKEN, PW_HEADERS, slides |

**Always use `/schedule-details?tap=video`** — it contains `MEDIA_TOKEN` and `PW_HEADERS` embedded in `<script>` tags.

## 5. Video URL API

```http
GET /v1/videos/video-url-details?mediaToken={TOKEN}&videoContainerType=DASH
Host: stream.testuk.org
```

- Called via **curl_cffi** with the real session cookie.
- Does **NOT** need the Bearer Authorization header — session cookie alone suffices.
- Returns: `url` (MPD), `drmType`, `keys` (array of `"key_id:key"` strings), `licenseUrl` (for Widevine), `pssh`, etc.

## 6. DRM Types

### ClearKey
- `keys` array has entries like `"f95f86375916d99f7a212ab66d29b905:ac8a9a5604bc5ba59220f704e5be1e8a"`
- Format: `key_id_in_hex:key_in_hex`
- ffmpeg decryption with `-cenc_decryption_key KEY_HEX`

### Widevine
- `drmType: "Widevine"`, `licenseUrl: "https://license-global.pallycon.com/..."` , `licenseToken`, `certificateUrl`
- BUT the `keys` array ALSO contains the pre-decrypted ClearKey keys (same format).
- So Widevine can be treated as ClearKey — extract key from `keys` array, decrypt with ffmpeg.
- No need to call the Widevine license server.

### Key extraction code (`core_download.py:extract_key`)
```python
def extract_key(video_data):
    # Priority: key_strings → keys array (first entry, split by ":")
    if "key_strings" in video_data and "--key " in video_data["key_strings"]:
        return video_data["key_strings"].replace("--key ", "").split(":")[1]
    if "keys" in video_data and video_data["keys"]:
        first = str(video_data["keys"][0])
        parts = first.split(":")
        return parts[1]  # return key (second part)
    return None
```

## 7. CDN — No Auth Required

- MPD segments served from `sec-prod-mediacdn.pw.live`
- CDN URLs already have auth baked into query params (`URLPrefix` base64-encoded)
- **No cookies, no Bearer token needed** — plain `aiohttp` GET works
- The `URLPrefix` contains the base CDN path; individual segments use `$Number$` template

## 8. api.penpencil.co

- Serves chapter/video metadata
- Uses Bearer token in PW_HEADERS (`authorization: Bearer eyJ...`)
- Works with plain `aiohttp` (no Cloudflare on this domain)
- Token expiry: stored in JWT `exp` claim (e.g., June 2026)
- Endpoints:
  - `/v2/batches/{batchId}/subject/{subjectId}/topics?page=N` — list chapters
  - `/v2/batches/{batchId}/subject/{subjectId}/contents?page=N&contentType=videos&tag={ch._id}` — list videos in chapter

## 9. Python Gotchas

### curl_cffi import
```python
from curl_cffi.requests import AsyncSession
# NOT from curl_cffi import AsyncSession
```

### UnboundLocalError in core_download.py
A `from urllib.parse import urlparse` inside the `download_video` function (in the RAW_URL branch) causes Python to treat `urlparse` as a **local variable** throughout the entire `download_video` function. When the `video_data_override` path is taken and later calls `urlparse(mpd_url)` (line ~251), it raises `UnboundLocalError` because the local import was never executed.

**Fix**: Remove the redundant inner import — the module-level `from urllib.parse import urlparse, parse_qs, urlencode` at the top of the file is sufficient.

## 10. Architecture Summary

```
batch_download.py
├── aiohttp (api.penpencil.co) → chapters / videos metadata
├── curl_cffi (stream.testuk.org) → schedule-details page → MEDIA_TOKEN → video URL API
└── core_download.py
    ├── aiohttp (sec-prod-mediacdn.pw.live) → MPD + segments
    └── ffmpeg → decrypt + mux → .mp4
```

No Playwright, no CDP, no browser automation.
