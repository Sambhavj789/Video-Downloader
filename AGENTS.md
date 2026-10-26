# AGENTS.md — Video-Downloader

Entry point for every AI agent and new human. Read in this order, then work.

1. `docs/00-index.md` — what this is, doc map, reading paths.
2. `docs/CURRENT_STATE.md` — what works, what is blocked, verified date.
3. `docs/CODEMAP.md` — which file owns what.
4. The one doc for your task (`SPEC`, `ARCHITECTURE`, `DEVELOPMENT`, …).

Do not read the whole repo. Do not read generated folders (`state/`, `logs/`, `.work/`,
`legacy/`) or the media library. If the docs and code disagree, treat that as a bug: fix the
smaller side and update the other in the same change.

## Hard rules

- **Never change `vd/names.py` sanitize/normalize rules.** 614 existing files depend on them;
  a "nicer" filename orphans the library. Migrating the library is a separate founder decision.
- **Never move, rename or delete library files.** This tool only creates missing files.
- Never touch `.env*`, `config/cookies.json`, `stream_cookies.json`, `token.txt`,
  `pw_headers.json`; never print or log cookie/token values (use `auth.cookie_summary`).
- Never scrape a different host, never call the site's write APIs, never post/upload anything.
- No new dependency without a founder decision; stdlib first (`vd/ui/server.py` is the example).
- Keep changes scoped; no drive-by refactors. Tests must never hit the network or the real
  library — use the `settings` fixture.
- Never push, merge, deploy or delete branches. The founder commits/merges.

## Verify (must pass before handoff)

```powershell
node verify-docs.js        # docs, links, CODEMAP coverage
python -m pytest tests -q  # 85 tests, hermetic
```

A task is done only when both are green and `docs/CURRENT_STATE.md` is current.

## Where things go

| Change | File |
|---|---|
| Behavior / command / endpoint | code + `docs/SPEC.md` |
| Layout / data flow | `docs/ARCHITECTURE.md` |
| New/moved file or symbol | `docs/CODEMAP.md` |
| Setup, tests, debug | `docs/DEVELOPMENT.md` |
| A choice with trade-offs | `docs/DECISIONS.md` |
| A repeated failure | `docs/TROUBLESHOOTING.md` |
| Status, limits, next | `docs/CURRENT_STATE.md` |
| User-visible change | `docs/CHANGELOG.md` |

## Definition of done

- [ ] Behavior matches `SPEC.md`; tests added/updated.
- [ ] `node verify-docs.js` and `python -m pytest tests -q` pass.
- [ ] `CODEMAP.md`, `CURRENT_STATE.md`, `CHANGELOG.md` updated.
- [ ] No secrets, no `config/`, no `state/`, no media in the diff.
