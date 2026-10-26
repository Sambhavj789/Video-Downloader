---
title: Video-Downloader — docs index
status: active
updated: 2026-10-25
---

# Video-Downloader

**30-second summary:** Personal offline sync tool for Sambhav's CA Inter lecture library
(`stream.testuk.org`). It reads the site's chapter/video/notes/DPP/slide list, compares it
with what is already on `G:\Knowledge\CA-Inter`, and downloads only what is missing into the
**existing** folder layout — a click-through browser UI for non-tech use, plus a CLI for the
same work.

**Owner:** Sambhav · **Priority:** P1 (blocks offline study) · **Verify:**
`node verify-docs.js && python -m pytest tests -q`

## Doc map

| Doc | Question it answers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | How is it built? Where does data flow? |
| [CODEMAP.md](CODEMAP.md) | Which file/symbol owns this behavior? |
| [SPEC.md](SPEC.md) | What exactly must it do (and not do)? |
| [DEVELOPMENT.md](DEVELOPMENT.md) | How do I run, test, debug and release it? |
| [CURRENT_STATE.md](CURRENT_STATE.md) | What works, what is blocked, what is next? |
| [DECISIONS.md](DECISIONS.md) | Why is it built this way? |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | It broke; what do I check first? |
| [CHANGELOG.md](CHANGELOG.md) | What changed, when? |
| [key-findings.md](key-findings.md) | Original site/DRM investigation (July 2026, historical) |

## Reading paths

- **First day:** this file → `CURRENT_STATE` → `ARCHITECTURE` → `CODEMAP`.
- **Small fix:** `CODEMAP` → code → `SPEC` if behavior changes.
- **New feature:** `SPEC` → `ARCHITECTURE` → `CODEMAP` → code → update all four.
- **Incident ("download fail"):** `TROUBLESHOOTING` → `logs/` → code.

## Ground rules

- One fact in one place; link instead of copying.
- Supersede, don't delete: set `status: superseded` and link the replacement.
- Every doc starts with front matter: `title`, `status`, `updated`.
- Dates `YYYY-MM-DD`; technical terms in English.
- Never write cookie/token values into docs, logs or tests.

## Status

- Last verified: `2026-10-25` — `pytest tests -q` → 85 tests; catalog built for 7 subjects;
  `python -m vd status --all` resolved every subject to its existing library folder.
- Blocked: free space on the library drive (`G:` ≈134 GB) vs. remaining download size; see
  `CURRENT_STATE.md`.
- Next: one small real download run (`--limit 1`) to prove mux + decrypt end to end.
