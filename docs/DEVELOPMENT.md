---
title: Development
status: active
updated: 2026-10-25
---

# Development

## Setup (Windows, Python 3.12)

```powershell
cd C:\Sambhav-OS\personal\Video-Downloader
python -m pip install -r requirements.txt
python -m playwright install chromium      # once per machine
python -m vd doctor                        # deps · ffmpeg · cookies · library · subjects
```

`ffmpeg` does not need to be installed separately — `imageio-ffmpeg` ships a binary
(`vd.dash.ffmpeg_exe()` finds it).

## First run

```powershell
# 1. register the subjects you care about (one link, or a whole batch)
python -m vd batch 68d63d619fb9929d48a19674            # list subjects of a batch
python -m vd link "<content link>" --dir "Audit"       # --dir only when the site name is wrong

# 2. session cookies (Chrome → DevTools → Application → Cookies → stream.testuk.org)
python -m vd session save cookies.json
python -m vd session check

# 3. catalog + what is missing
python -m vd catalog --all
python -m vd status --all

# 4. download (dry run first)
python -m vd download --all --kinds videos --dry-run
python -m vd download --all --kinds videos --limit 1 --yes
```

For non-tech use: double-click `start.bat` (or `python -m vd ui`). Browser opens on
`http://127.0.0.1:7878/`.

## Tests

```powershell
python -m pytest tests -q          # 85 tests, ~4 s, no network, no real library
node verify-docs.js                # docs presence, front matter, links, CODEMAP coverage
```

Tests are hermetic: `tests/conftest.py` builds a throwaway library in `tmp_path`, and the
server tests patch every store. Nothing reads `config/cookies.json`.

Add a test when you touch: name rules, folder matching, plan status logic, MPD parsing,
schedule parsing, or an `/api/*` handler.

## Debugging

| Need | Command |
|---|---|
| What does the proxy return? | `python tools/probe.py "/batches/<id>/subject/<sid>/topics?page=1"` |
| Subject ids of a batch | `python -m vd batch <batchId>` (or `tools/probe.py .../details --v3`) |
| What does a schedule page embed? | `python tools/fetch_page.py "/schedule-details?..." page.html` then grep `NOTES` |
| Which items are missing? | `python -m vd status --subject <key>` → `state/reports/<key>.md` |
| Why did a video fail? | `logs/run-*.log` (UI downloads tee here) and `state/progress/<key>.json` |
| Leftover temp segments | `python -m vd clean` |

`vd.dash` keeps the ffmpeg stderr tail in the item error, so a mux failure names its cause.

## Release / handoff

1. `python -m pytest tests -q` green.
2. `node verify-docs.js` green.
3. Update `docs/CURRENT_STATE.md` and add a `docs/CHANGELOG.md` line.
4. `git status` — no `config/`, no `state/`, no cookies, no media. Then commit
   (branch rules live in the HQ vault: no pushes, the founder merges).

## Conventions

- Python 3.12, stdlib typing (`X | None`), no async framework beyond `aiohttp`/`asyncio`.
- Every user-facing message is Hinglish; code comments/docstrings in English.
- One module = one responsibility (see `CODEMAP.md`); no circular imports inside `vd`.
- New dependency → founder decision first (`docs/DECISIONS.md`).
