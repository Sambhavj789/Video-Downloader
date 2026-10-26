"""Dev helper: show what a stream-domain page embeds (arrays + subject names).

    python tools/probe_page.py "/content?batchId=..&subjectId=.."

Prints only structure and names — never cookie values.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vd import auth  # noqa: E402
from vd.stream import STREAM_BASE, StreamClient  # noqa: E402

ARRAY_NAMES = re.compile(r"(?:const|var|let|window\.)\s+([A-Z_][A-Z0-9_]{2,})\s*=\s*(\[|\{)")


async def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = argv[1]
    needle = argv[2] if len(argv) > 2 else ""
    async with StreamClient(auth.load_cookies()) as client:
        status, body = await client.get_text(f"{STREAM_BASE}{path}")
    print("status:", status, "| bytes:", len(body))
    print("arrays/objects:", sorted(set(ARRAY_NAMES.findall(body)) and {m[0] for m in ARRAY_NAMES.findall(body)}))
    if needle:
        for match in re.finditer(re.escape(needle), body):
            start = max(0, match.start() - 160)
            print("---", re.sub(r"\s+", " ", body[start:match.end() + 260]))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv)))
