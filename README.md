# Video-Downloader

Personal offline sync tool for Sambhav's CA Inter lecture library (`stream.testuk.org`).
It reads the site's chapter/video/notes/DPP/slide list, compares it with what is already on
`G:\Knowledge\CA-Inter`, and downloads **only what is missing** into the existing folders —
so 333 GB of finished lectures are never touched or renamed.

## Quick start

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m vd doctor            # deps · ffmpeg · cookies · library · subjects
python -m vd ui                # or double-click start.bat
```

Browser opens on `http://127.0.0.1:7878/`: pick a subject → **Catalog refresh** →
tick what is missing → **Download**.

CLI equivalent:

```powershell
python -m vd batch 68d63d619fb9929d48a19674          # see the batch's subjects
python -m vd catalog --all
python -m vd status --all                            # what's bacha hua
python -m vd download --all --kinds notes,dpp,documents --yes   # 1. PDFs + question banks
python -m vd download --all --kinds videos --yes                # 2. lectures jo bache hain
```

Notes first, videos baad me — PDFs chhote hain aur turant kaam ke, videos GB khaate hain.
Order sirf preference hai: dono commands resumable hain, jo file already hai use skip karte hain.

## Verify

```powershell
node verify-docs.js
python -m pytest tests -q
```

## Docs

Read [`docs/00-index.md`](docs/00-index.md) first — architecture, spec, code map, decisions,
troubleshooting, current state. AI agents start at [`AGENTS.md`](AGENTS.md).

## Status

Engine + UI work; 7 CA Inter subjects registered; every subject resolves to its existing
library folder. Details and open blockers in [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md).
