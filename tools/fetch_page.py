"""Dev helper: fetch a stream-domain page and save the raw HTML for grepping.

    python tools/fetch_page.py "/subjects?batchId=..&batchName=.." [out.html]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vd import auth  # noqa: E402
from vd.stream import STREAM_BASE, StreamClient  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / ".dev-pages"


async def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = argv[1]
    name = argv[2] if len(argv) > 2 else "page.html"
    async with StreamClient(auth.load_cookies()) as client:
        status, body = await client.get_text(f"{STREAM_BASE}{path}")
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / name
    out.write_text(body, encoding="utf-8")
    print(f"status {status} · {len(body)} bytes · {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv)))
